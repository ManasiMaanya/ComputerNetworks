"""RIP-like hop count and OSPF-like SPF (Phase 2).

RIP-like:  Dijkstra with unit cost per link (fewest hops).
OSPF-like: Dijkstra on a per-link cost chosen by config `ospf_cost`:
    "delay"             cost = delay (ms)
    "inverse_bandwidth" cost = ospf_reference_bandwidth_bps / (bandwidth_Mbps * 1e6)
                        (the classic 10^8 / bandwidth; kept as a float, no Cisco floor to 1)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx

from ..errors import NoPathError, RoutingError
from ..features.path_features import check_endpoints


@dataclass(frozen=True)
class RouteResult:
    method: str
    src: str
    dst: str
    path: tuple[str, ...]
    cost: float
    cost_metric: str

    @property
    def hops(self) -> int:
        return len(self.path) - 1

    @property
    def label(self) -> str:
        return "-".join(self.path)


def ospf_link_cost(data: dict, strategy: str, reference_bps: float, edge: str = "edge") -> float:
    if strategy == "delay":
        cost = data.get("delay")
    elif strategy == "inverse_bandwidth":
        bandwidth = data.get("bandwidth")
        if bandwidth is None:
            raise RoutingError(f"{edge}: missing 'bandwidth' for inverse_bandwidth cost")
        if not isinstance(bandwidth, (int, float)) or not bandwidth > 0:
            raise RoutingError(f"{edge}: bandwidth must be > 0 for inverse_bandwidth cost, got {bandwidth!r}")
        cost = reference_bps / (float(bandwidth) * 1e6)
    else:
        raise RoutingError(f"unknown ospf_cost strategy '{strategy}' (use 'delay' or 'inverse_bandwidth')")
    if cost is None:
        raise RoutingError(f"{edge}: missing '{strategy}' attribute for OSPF cost")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
        raise RoutingError(f"{edge}: OSPF cost must be a finite number >= 0 for Dijkstra, got {cost!r}")
    return float(cost)


def ospf_weighted_graph(graph: nx.Graph, strategy: str, reference_bps: float) -> nx.Graph:
    """Copy of the topology with a validated `ospf_weight` on every edge."""
    weighted = graph.__class__()
    weighted.add_nodes_from(graph.nodes())
    for u, v, data in graph.edges(data=True):
        weighted.add_edge(u, v, ospf_weight=ospf_link_cost(data, strategy, reference_bps, f"edge {u}-{v}"))
    return weighted


def _dijkstra(graph: nx.Graph, src: str, dst: str, weight) -> tuple[float, list]:
    try:
        return nx.single_source_dijkstra(graph, src, dst, weight=weight)
    except nx.NetworkXNoPath:
        raise NoPathError(f"no path from {src} to {dst}: nodes are disconnected") from None


def rip_route(graph: nx.Graph, src, dst) -> RouteResult:
    src, dst = check_endpoints(graph, src, dst)
    cost, path = _dijkstra(graph, src, dst, weight=lambda u, v, d: 1)
    return RouteResult("RIP", src, dst, tuple(map(str, path)), float(cost), "hops")


def ospf_route(graph: nx.Graph, src, dst, strategy: str = "delay",
               reference_bps: float = 1e8) -> RouteResult:
    src, dst = check_endpoints(graph, src, dst)
    weighted = ospf_weighted_graph(graph, strategy, reference_bps)
    cost, path = _dijkstra(weighted, src, dst, weight="ospf_weight")
    metric = "delay_ms" if strategy == "delay" else "ref_bw/bandwidth"
    return RouteResult("OSPF", src, dst, tuple(map(str, path)), float(cost), metric)


def ospf_route_from_config(graph: nx.Graph, src, dst, cfg: dict) -> RouteResult:
    return ospf_route(graph, src, dst, cfg["ospf_cost"], float(cfg["ospf_reference_bandwidth_bps"]))
