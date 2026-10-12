"""Candidate paths and path feature vectors (Phase 1).

Candidates: Yen's k-shortest simple paths (networkx.shortest_simple_paths) ordered by hop count,
by delay, or both interleaved ("mixed", default); see candidate_paths. Paths longer than max_hops
are never returned. Ties keep Yen's deterministic order.

FEATURE_COLUMNS is the canonical, ordered schema used by training, inference, SHAP/LIME,
comparison, and simulation. See docs/xai-dynamic-routing-methods.md (repo root) for units and aggregation rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice

import networkx as nx
import numpy as np
import pandas as pd

from ..errors import NoPathError, RoutingError, TopologyError
from ..topology.load import EDGE_ATTRS, check_metric

FEATURE_COLUMNS: tuple[str, ...] = (
    "hops",
    "sum_delay",
    "max_delay",
    "min_bandwidth",
    "max_security_risk",
    "mean_congestion",
    "sum_loss",
    "max_loss",
    "mean_energy",
    "max_utilization",
    "max_queue",
    "min_reliability",
)

FEATURE_UNITS: dict[str, str] = {
    "hops": "links",
    "sum_delay": "ms",
    "max_delay": "ms",
    "min_bandwidth": "Mbps",
    "max_security_risk": "score 0-1",
    "mean_congestion": "fraction 0-1",
    "sum_loss": "fraction (additive)",
    "max_loss": "fraction 0-1",
    "mean_energy": "relative units",
    "max_utilization": "fraction 0-1",
    "max_queue": "packets",
    "min_reliability": "probability 0-1",
}


@dataclass
class PathCandidate:
    path_id: int
    nodes: tuple[str, ...]
    features: dict[str, float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return "-".join(self.nodes)

    def vector(self) -> np.ndarray:
        return np.array([self.features[c] for c in FEATURE_COLUMNS], dtype=float)


def check_endpoints(graph: nx.Graph, src, dst) -> tuple[str, str]:
    src, dst = str(src), str(dst)
    missing = [n for n in (src, dst) if n not in graph]
    if missing:
        sample = ", ".join(sorted(map(str, graph.nodes()))[:10])
        raise RoutingError(f"unknown node(s) {missing}; graph nodes include: {sample}")
    if src == dst:
        raise RoutingError(f"source and destination are the same node '{src}'")
    return src, dst


def edge_metrics(graph: nx.Graph, u, v) -> dict[str, float]:
    if not graph.has_edge(u, v):
        raise TopologyError(f"path uses edge {u}-{v} which is not in the graph")
    data = graph.edges[u, v]
    missing = [k for k in EDGE_ATTRS if k not in data]
    if missing:
        raise TopologyError(f"edge {u}-{v}: missing required attributes {missing}")
    return {k: check_metric(k, data[k], f"edge {u}-{v}") for k in EDGE_ATTRS}


def extract_features(graph: nx.Graph, path) -> dict[str, float]:
    """Aggregate per-link metrics along `path` (sequence of >= 2 nodes)."""
    nodes = [str(n) for n in path]
    if len(nodes) < 2:
        raise RoutingError(f"path must contain at least two nodes, got {nodes}")
    if len(set(nodes)) != len(nodes):
        raise RoutingError(f"path {nodes} repeats a node (only simple paths are allowed)")
    links = [edge_metrics(graph, u, v) for u, v in zip(nodes, nodes[1:])]
    col = {k: np.array([link[k] for link in links], dtype=float) for k in EDGE_ATTRS}
    features = {
        "hops": float(len(links)),
        "sum_delay": float(col["delay"].sum()),
        "max_delay": float(col["delay"].max()),
        "min_bandwidth": float(col["bandwidth"].min()),
        "max_security_risk": float(col["security_risk"].max()),
        "mean_congestion": float(col["congestion"].mean()),
        "sum_loss": float(col["loss"].sum()),
        "max_loss": float(col["loss"].max()),
        "mean_energy": float(col["energy"].mean()),
        "max_utilization": float(col["utilization"].max()),
        "max_queue": float(col["queue"].max()),
        "min_reliability": float(col["reliability"].min()),
    }
    bad = [k for k, val in features.items() if not np.isfinite(val)]
    if bad:
        raise TopologyError(f"path {'-'.join(nodes)}: non-finite features {bad}")
    return features


def path_quality_metrics(graph: nx.Graph, path) -> dict[str, float]:
    """Extra end-to-end metrics for reports (not model inputs)."""
    nodes = [str(n) for n in path]
    links = [edge_metrics(graph, u, v) for u, v in zip(nodes, nodes[1:])]
    delivery = float(np.prod([1.0 - link["loss"] for link in links]))
    return {
        "path_loss": 1.0 - delivery,
        "path_reliability": float(np.prod([link["reliability"] for link in links])),
    }


CANDIDATE_STRATEGIES = ("hops", "delay", "mixed")
DELAY_SCAN_FACTOR = 20  # delay-ordered Yen inspects at most k * this many paths to find k within max_hops


def _yen(graph: nx.Graph, src: str, dst: str, k: int, max_hops: int, weight: str | None) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    try:
        for path in islice(nx.shortest_simple_paths(graph, src, dst, weight=weight), k * DELAY_SCAN_FACTOR):
            if len(path) - 1 > max_hops:
                if weight is None:  # hop-ordered: every later path is at least as long
                    break
                continue
            paths.append(tuple(path))
            if len(paths) == k:
                break
    except nx.NetworkXNoPath:
        raise NoPathError(f"no path from {src} to {dst}: nodes are disconnected") from None
    return paths


def candidate_paths(graph: nx.Graph, src, dst, k: int, max_hops: int,
                    strategy: str = "mixed") -> list[tuple[str, ...]]:
    """Up to k distinct simple paths with <= max_hops links.

    hops:  Yen k-shortest by hop count.
    delay: Yen k-shortest by summed delay.
    mixed: alternate hop-ordered and delay-ordered lists, dropping duplicates, until k paths,
           so the fewest-hop and the lowest-delay path are always both candidates.
    """
    if k < 1 or max_hops < 1:
        raise RoutingError(f"k ({k}) and max_hops ({max_hops}) must both be >= 1")
    if strategy not in CANDIDATE_STRATEGIES:
        raise RoutingError(f"unknown candidate strategy '{strategy}'; use one of {CANDIDATE_STRATEGIES}")
    src, dst = check_endpoints(graph, src, dst)
    by_hops = _yen(graph, src, dst, k, max_hops, None) if strategy in ("hops", "mixed") else []
    by_delay = _yen(graph, src, dst, k, max_hops, "delay") if strategy in ("delay", "mixed") else []
    if strategy == "hops":
        paths = by_hops
    elif strategy == "delay":
        paths = by_delay
    else:
        paths = []
        for i in range(max(len(by_hops), len(by_delay))):
            for source in (by_hops, by_delay):
                if i < len(source) and source[i] not in paths and len(paths) < k:
                    paths.append(source[i])
    if not paths:
        raise NoPathError(f"no path from {src} to {dst} within max_hops={max_hops}")
    return paths


def enumerate_candidates(graph: nx.Graph, src, dst, k: int, max_hops: int,
                         strategy: str = "mixed") -> list[PathCandidate]:
    return [
        PathCandidate(path_id=i, nodes=path, features=extract_features(graph, path))
        for i, path in enumerate(candidate_paths(graph, src, dst, k, max_hops, strategy))
    ]


def candidates_frame(candidates: list[PathCandidate], src, dst) -> pd.DataFrame:
    rows = [{"src": str(src), "dst": str(dst), "path_id": c.path_id, "path": c.label, **c.features}
            for c in candidates]
    return pd.DataFrame(rows, columns=["src", "dst", "path_id", "path", *FEATURE_COLUMNS])


def feature_matrix(candidates: list[PathCandidate]) -> pd.DataFrame:
    """Model input: exactly FEATURE_COLUMNS, in order, one row per candidate."""
    return pd.DataFrame([c.features for c in candidates], columns=list(FEATURE_COLUMNS)).astype(float)
