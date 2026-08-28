"""Load an undirected topology JSON into a NetworkX graph."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

EDGE_ATTRS = (
    "delay",
    "bandwidth",
    "congestion",
    "loss",
    "energy",
    "security_risk",
    "utilization",
    "queue",
    "reliability",
)


def load_graph(path: str | Path) -> nx.Graph:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    graph = nx.DiGraph() if data.get("directed") else nx.Graph()
    graph.add_nodes_from(data["nodes"])
    for edge in data["edges"]:
        attrs = {key: edge[key] for key in EDGE_ATTRS if key in edge}
        graph.add_edge(edge["u"], edge["v"], **attrs)
    return graph
