"""Q-routing baseline (Boyan & Littman, 1994) for the comparison in src/evaluate/compare.py.

RIP (hop count) and OSPF (src/routing/baselines.py) both route on a *static* cost: RIP ignores the
topology's numbers entirely, and OSPF's default cost is the topology's fixed `delay`. Neither reacts
to live traffic. The project's own research gap (docs/xai-dynamic-routing-overview.md, "classical
IGPs stay on fixed metrics") calls for a classical point of comparison that *does* react to traffic,
distinct from the AI/AI-BB models that score many criteria at once (delay, loss, congestion,
security_risk, ...). Q-routing is that method: each node keeps a table estimating the delivery cost
to each destination via each neighbour, and greedily forwards to whichever neighbour's estimate is
lowest, so its path choice shifts as congestion shifts even though the topology never changes.

This project's traffic model (src/simulate/traffic.py) only ever varies `congestion`, `loss`, and
`security_risk` -- `delay` is a static topology attribute. A Q-routing that minimised delay alone
would therefore be blind to the very dynamics it exists to react to, and degenerate into OSPF's
default cost. So here Q-routing's per-hop cost is defined as:

    cost(u, v) = delay_ms(u, v) * (1 + congestion(u, v))

keeping it a single-objective, delay-and-congestion-aware classical baseline -- reactive like the
AI models, but, unlike them, blind to loss/security_risk/bandwidth/etc.

Training: the original algorithm updates its tables online, with routers exchanging estimates as
real packets are forwarded. To fit this project's existing baseline pattern -- RIP/OSPF take no
training step, and the AI models are trained once per topology, not once per query -- the Q-table
here is trained once per topology, offline, by replaying the same synthetic traffic trace already
used for AI training (`src.simulate.traffic.generate_trace`) and, at every step, sweeping every
(node, destination, neighbour) triple with a TD(0) backup:

    Q[x][d][y] <- Q[x][d][y] + lr * (cost(x, y) + Q[y][d][best-neighbour-of-y-toward-d] - Q[x][d][y])
    (the second term is 0 when y is d itself)

Routing is then greedy and stateless: at each hop, go to argmin_y Q[x][dst][y] among x's current
neighbours, for up to `max_hops` steps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx

from ..errors import NoPathError, RoutingError
from ..features.path_features import check_endpoints
from ..simulate.traffic import TrafficParams, generate_trace
from .baselines import RouteResult

COST_METRIC = "delay_ms*(1+congestion)"


def qrouting_edge_cost(data: dict, where: str = "edge") -> float:
    """Q-routing's per-hop cost: delay scaled up by how congested the link currently is."""
    for name in ("delay", "congestion"):
        value = data.get(name)
        if value is None:
            raise RoutingError(f"{where}: missing '{name}' for Q-routing cost")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise RoutingError(f"{where}: '{name}' must be a finite number >= 0 for Q-routing cost, got {value!r}")
    return float(data["delay"]) * (1.0 + float(data["congestion"]))


@dataclass
class QRoutingModel:
    """q[node][dst][neighbour] -> estimated cost of delivering a packet from `node` to `dst` by
    forwarding first to `neighbour`. `nodes` is the training topology's node set, kept only so a
    model routed on a topology it was never trained on fails with a clear message rather than a
    silently-empty table."""

    q: dict[str, dict[str, dict[str, float]]]
    nodes: frozenset[str]

    def estimate(self, node: str, dst: str, neighbor: str) -> float:
        return self.q.get(node, {}).get(dst, {}).get(neighbor, math.inf)


def train_qrouting(graph: nx.Graph, cfg: dict, *, steps: int | None = None, seed: int | None = None,
                   traffic_params: TrafficParams | None = None) -> QRoutingModel:
    """Train one Q-table for `graph` (see module docstring for the training scheme).

    `steps`/`seed` default to config `qrouting.train_steps`/`qrouting.seed`; `traffic_params`
    defaults to the config's `traffic` block (the same traffic model the AI models train on).
    Callers that want a smaller trace or a frozen (noise-free) one for testing can override either.
    """
    qcfg = cfg["qrouting"]
    steps = qcfg["train_steps"] if steps is None else steps
    seed = qcfg["seed"] if seed is None else seed
    lr, discount = qcfg["learning_rate"], qcfg["discount"]
    params = traffic_params if traffic_params is not None else TrafficParams.from_config(cfg.get("traffic"))
    nodes = tuple(sorted(map(str, graph.nodes())))

    q: dict[str, dict[str, dict[str, float]]] = {n: {} for n in nodes}

    def estimate(x: str, d: str, y: str) -> float:
        return q[x].get(d, {}).get(y, 0.0)

    for snapshot in generate_trace(graph, steps, seed, params):
        cost: dict[tuple[str, str], float] = {}
        neighbors: dict[str, list[str]] = {}
        for u, v, data in snapshot.edges(data=True):
            u, v = str(u), str(v)
            c = qrouting_edge_cost(data, f"edge {u}-{v}")
            cost[(u, v)] = cost[(v, u)] = c
            neighbors.setdefault(u, []).append(v)
            neighbors.setdefault(v, []).append(u)

        for dst in nodes:
            for x in nodes:
                if x == dst:
                    continue
                for y in neighbors.get(x, []):
                    best_from_y = 0.0 if y == dst else min(
                        (estimate(y, dst, z) for z in neighbors.get(y, [])), default=0.0)
                    target = cost[(x, y)] + discount * best_from_y
                    q[x].setdefault(dst, {})
                    q[x][dst][y] = estimate(x, dst, y) + lr * (target - estimate(x, dst, y))

    return QRoutingModel(q=q, nodes=frozenset(nodes))


def qroute_route(graph: nx.Graph, src, dst, model: QRoutingModel, max_hops: int | None = None) -> RouteResult:
    """Greedy hop-by-hop forwarding using `model`'s Q-table (see module docstring)."""
    src, dst = check_endpoints(graph, src, dst)
    if not nx.has_path(graph, src, dst):
        raise NoPathError(f"no path from {src} to {dst}: nodes are disconnected")
    limit = max_hops if max_hops is not None else max(len(model.nodes), graph.number_of_nodes())

    path, visited, current, total = [src], {src}, src, 0.0
    while current != dst:
        if len(path) - 1 >= limit:
            raise RoutingError(f"Q-routing: no route from {src} to {dst} converged within {limit} hops")
        neighbors = [str(n) for n in graph.neighbors(current)]
        if not neighbors:
            raise RoutingError(f"Q-routing: {current} has no outgoing edges while routing {src} to {dst}")
        best = min(neighbors, key=lambda y: model.estimate(current, dst, y))
        if not math.isfinite(model.estimate(current, dst, best)):
            raise RoutingError(f"Q-routing: no trained estimate at {current} toward {dst}; "
                               f"retrain the model on this topology")
        if best in visited:
            raise RoutingError(f"Q-routing: forwarding loop at {best} while routing {src} to {dst} "
                               f"(the table has not converged for this pair)")
        total += qrouting_edge_cost(graph[current][best], f"edge {current}-{best}")
        visited.add(best)
        path.append(best)
        current = best
    return RouteResult("Q-ROUTE", src, dst, tuple(path), float(total), COST_METRIC)
