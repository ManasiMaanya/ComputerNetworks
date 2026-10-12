"""Time-varying link conditions: the traffic model behind training labels and scenarios.

Three edge metrics change over time - congestion, loss, security_risk. Every other metric is
static. Each step, for every edge and dynamic metric x with baseline mu (its value in the input
topology):

    x <- x + reversion * (mu - x) + noise * N(0, 1)   [+ burst]

then clamped to its METRIC_SPEC range. On top of that, with probability `burst_prob` an edge gets
a congestion burst (congestion and loss jump together by burst_size * U(0.5, 1.5)), and with
probability `incident_prob` a security incident (security_risk jumps by incident_size * U(0.5, 1.5)).

Mean reversion makes bursts and incidents transient: they decay back toward the baseline over a
few steps (incidents more slowly, given their lower reversion). That is what makes recent history
informative - a path that looks bad now because of a burst usually recovers, while one that has
been bad for several steps is more likely bad at its baseline. The parameters (config `traffic`)
are a documented modelling assumption, not fitted to measured traffic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from ..errors import ConfigError
from ..topology.load import clamp_metric

DYNAMIC_METRICS = ("congestion", "loss", "security_risk")


@dataclass(frozen=True)
class TrafficParams:
    reversion: dict[str, float] = field(
        default_factory=lambda: {"congestion": 0.25, "loss": 0.25, "security_risk": 0.10})
    noise: dict[str, float] = field(
        default_factory=lambda: {"congestion": 0.03, "loss": 0.003, "security_risk": 0.01})
    burst_prob: float = 0.06
    burst_size: dict[str, float] = field(default_factory=lambda: {"congestion": 0.30, "loss": 0.03})
    incident_prob: float = 0.02
    incident_size: float = 0.30

    @classmethod
    def from_config(cls, block: dict | None, where: str = "traffic") -> "TrafficParams":
        """Build from a config `traffic` block; missing keys keep their defaults."""
        if not block:
            return cls()
        if not isinstance(block, dict):
            raise ConfigError(f"{where}: must be an object")
        unknown = set(block) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
        params = cls(**block)
        for name in ("reversion", "noise"):
            values = getattr(params, name)
            if set(values) != set(DYNAMIC_METRICS):
                raise ConfigError(f"{where}.{name}: needs exactly {DYNAMIC_METRICS}")
            for metric, value in values.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    raise ConfigError(f"{where}.{name}.{metric}: must be a number >= 0")
            if name == "reversion" and any(v > 1 for v in values.values()):
                raise ConfigError(f"{where}.reversion: values must be <= 1")
        for name in ("burst_prob", "incident_prob"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ConfigError(f"{where}.{name}: must be in [0, 1]")
        if set(params.burst_size) - {"congestion", "loss"}:
            raise ConfigError(f"{where}.burst_size: only 'congestion' and 'loss' are allowed")
        return params


class TrafficModel:
    """Steps a graph's dynamic metrics; baselines are taken from `base_graph`."""

    def __init__(self, base_graph: nx.Graph, params: TrafficParams | None = None):
        self.params = params or TrafficParams()
        self._baseline = {(u, v): {m: float(d[m]) for m in DYNAMIC_METRICS}
                          for u, v, d in base_graph.edges(data=True)}

    def step(self, graph: nx.Graph, rng: np.random.Generator) -> list[dict]:
        """Advance `graph` one step in place; return the changes as {edge, metric, old, new, cause}."""
        p = self.params
        changes: list[dict] = []
        for u, v, data in sorted(graph.edges(data=True), key=lambda e: (str(e[0]), str(e[1]))):
            baseline = self._baseline[(u, v)] if (u, v) in self._baseline else self._baseline[(v, u)]
            burst = rng.random() < p.burst_prob
            incident = rng.random() < p.incident_prob
            for metric in DYNAMIC_METRICS:
                old = float(data[metric])
                new = old + p.reversion[metric] * (baseline[metric] - old)
                new += p.noise[metric] * rng.standard_normal()
                if burst and metric in p.burst_size:
                    new += p.burst_size[metric] * rng.uniform(0.5, 1.5)
                if incident and metric == "security_risk":
                    new += p.incident_size * rng.uniform(0.5, 1.5)
                new = clamp_metric(metric, new)
                if abs(new - old) > 1e-12:
                    cause = ("burst" if burst and metric in p.burst_size else
                             "incident" if incident and metric == "security_risk" else "traffic")
                    data[metric] = new
                    changes.append({"edge": f"{u}-{v}", "metric": metric, "old": old, "new": new,
                                    "cause": cause})
        return changes


def generate_trace(graph: nx.Graph, steps: int, seed: int,
                   params: TrafficParams | None = None) -> list[nx.Graph]:
    """`steps + 1` snapshots: the input graph (t=0) then one per step. The input is not modified."""
    model = TrafficModel(graph, params)
    rng = np.random.default_rng(seed)
    current = graph.copy()
    snapshots = [graph.copy()]
    for _ in range(steps):
        model.step(current, rng)
        snapshots.append(current.copy())
    return snapshots
