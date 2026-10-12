"""Load a topology JSON into a validated NetworkX graph.

JSON shape::

    {"directed": false,
     "nodes": ["R1", {"id": "R2", "role": "core"}, ...],
     "edges": [{"u": "R1", "v": "R2", "delay": 5, "bandwidth": 100, ...}, ...]}

Every edge must carry all of EDGE_ATTRS with finite values inside METRIC_SPEC ranges.
Extra edge/node keys are kept on the graph unchanged (never silently dropped).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from ..errors import TopologyError

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


@dataclass(frozen=True)
class MetricSpec:
    low: float
    high: float
    low_inclusive: bool
    high_inclusive: bool
    unit: str
    meaning: str

    def contains(self, value: float) -> bool:
        above = value >= self.low if self.low_inclusive else value > self.low
        below = value <= self.high if self.high_inclusive else value < self.high
        return above and below

    def describe(self) -> str:
        lo = "[" if self.low_inclusive else "("
        hi = "]" if self.high_inclusive else ")"
        return f"{lo}{self.low:g}, {self.high:g}{hi}"


INF = math.inf
METRIC_SPEC: dict[str, MetricSpec] = {
    "delay": MetricSpec(0, INF, True, False, "ms", "one-way link latency"),
    "bandwidth": MetricSpec(0, INF, False, False, "Mbps", "link capacity"),
    "congestion": MetricSpec(0, 1, True, True, "fraction", "congestion level"),
    "loss": MetricSpec(0, 1, True, False, "fraction", "packet loss probability on the link"),
    "energy": MetricSpec(0, INF, True, False, "relative units", "energy cost of using the link"),
    "security_risk": MetricSpec(0, 1, True, True, "score", "lab risk score of the link"),
    "utilization": MetricSpec(0, 1, True, True, "fraction", "load / capacity"),
    "queue": MetricSpec(0, INF, True, False, "packets", "queue length at the link"),
    "reliability": MetricSpec(0, 1, False, True, "probability", "probability the link stays up"),
}


def check_metric(name: str, value, where: str) -> float:
    """Return `value` as float or raise TopologyError naming the edge and the allowed range."""
    spec = METRIC_SPEC[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TopologyError(f"{where}: '{name}' must be a number, got {value!r}")
    value = float(value)
    if not math.isfinite(value):
        raise TopologyError(f"{where}: '{name}' must be finite, got {value}")
    if not spec.contains(value):
        raise TopologyError(f"{where}: '{name}'={value:g} outside allowed range {spec.describe()} {spec.unit}")
    return value


_CLAMP = {"bandwidth": (0.1, INF), "loss": (0.0, 0.99), "reliability": (0.01, 1.0)}


def clamp_metric(name: str, value: float) -> float:
    """Clip a simulated/estimated value into the valid METRIC_SPEC range for `name`."""
    spec = METRIC_SPEC[name]
    low, high = _CLAMP.get(name, (spec.low, spec.high))
    return float(min(max(value, low), high))


def validate_graph_metrics(graph: nx.Graph, where: str = "graph") -> None:
    """Check every edge of an in-memory graph (used after simulation updates or GML mapping)."""
    for u, v, data in graph.edges(data=True):
        edge = f"{where} edge {u}-{v}"
        missing = [k for k in EDGE_ATTRS if k not in data]
        if missing:
            raise TopologyError(f"{edge}: missing required attributes {missing}")
        for key in EDGE_ATTRS:
            data[key] = check_metric(key, data[key], edge)


def _node_entries(raw_nodes, where: str) -> list[tuple[str, dict]]:
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise TopologyError(f"{where}: 'nodes' must be a non-empty list")
    entries: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_nodes):
        if isinstance(item, dict):
            if "id" not in item:
                raise TopologyError(f"{where}: node #{index} is an object without 'id'")
            node_id, attrs = item["id"], {k: v for k, v in item.items() if k != "id"}
        else:
            node_id, attrs = item, {}
        if isinstance(node_id, bool) or not isinstance(node_id, (str, int)) or str(node_id).strip() == "":
            raise TopologyError(f"{where}: node #{index} has invalid id {node_id!r}")
        node_id = str(node_id)
        if node_id in seen:
            raise TopologyError(f"{where}: duplicate node id '{node_id}'")
        seen.add(node_id)
        entries.append((node_id, attrs))
    return entries


def graph_from_dict(data: dict, where: str = "topology") -> nx.Graph:
    """Build and validate a graph from the JSON-shaped dict described in the module docstring."""
    if not isinstance(data, dict):
        raise TopologyError(f"{where}: top level must be a JSON object")
    for key in ("nodes", "edges"):
        if key not in data:
            raise TopologyError(f"{where}: missing top-level key '{key}'")
    directed = data.get("directed", False)
    if not isinstance(directed, bool):
        raise TopologyError(f"{where}: 'directed' must be true or false, got {directed!r}")

    graph: nx.Graph = nx.DiGraph() if directed else nx.Graph()
    graph.graph.update({"name": data.get("name", Path(where).stem), "source": where, "directed": directed})
    for node_id, attrs in _node_entries(data["nodes"], where):
        graph.add_node(node_id, **attrs)

    if not isinstance(data["edges"], list):
        raise TopologyError(f"{where}: 'edges' must be a list")
    for index, edge in enumerate(data["edges"]):
        label = f"{where} edge #{index}"
        if not isinstance(edge, dict):
            raise TopologyError(f"{label}: must be an object, got {type(edge).__name__}")
        for key in ("u", "v"):
            if key not in edge:
                raise TopologyError(f"{label}: missing endpoint '{key}'")
        u, v = str(edge["u"]), str(edge["v"])
        label = f"{where} edge {u}-{v}"
        for endpoint in (u, v):
            if endpoint not in graph:
                raise TopologyError(f"{label}: endpoint '{endpoint}' is not in 'nodes'")
        if u == v:
            raise TopologyError(f"{label}: self-loops are not allowed")
        if graph.has_edge(u, v):
            raise TopologyError(f"{label}: duplicate edge")
        missing = [k for k in EDGE_ATTRS if k not in edge]
        if missing:
            raise TopologyError(f"{label}: missing required attributes {missing}")
        attrs = {k: val for k, val in edge.items() if k not in ("u", "v")}
        for key in EDGE_ATTRS:
            attrs[key] = check_metric(key, edge[key], label)
        graph.add_edge(u, v, **attrs)

    components = (nx.number_weakly_connected_components(graph) if directed
                  else nx.number_connected_components(graph))
    graph.graph["components"] = components
    return graph


def load_graph(path: str | Path, *, require_connected: bool = False) -> nx.Graph:
    """Load a JSON topology. Raises TopologyError with the file name and the offending key/edge."""
    path = Path(path)
    if not path.is_file():
        raise TopologyError(f"topology file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TopologyError(f"{path}: invalid JSON at line {exc.lineno} col {exc.colno}: {exc.msg}") from exc
    except UnicodeDecodeError as exc:
        raise TopologyError(f"{path}: file is not UTF-8 text") from exc
    graph = graph_from_dict(data, where=path.name)
    graph.graph["source"] = str(path)
    if require_connected and graph.graph["components"] != 1:
        raise TopologyError(f"{path}: graph has {graph.graph['components']} disconnected components")
    return graph


def load_topology(path: str | Path, cfg: dict | None = None) -> nx.Graph:
    """Dispatch on file type: .json (project), .gml/.graphml (Topology Zoo), .txt (SNDlib native)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_graph(path)
    if suffix in (".gml", ".graphml"):
        from .zoo import load_zoo

        return load_zoo(path, cfg)
    if suffix == ".txt":
        from .sndlib import load_sndlib

        return load_sndlib(path, cfg)
    raise TopologyError(f"{path}: unsupported topology format '{suffix}' (use .json, .gml, .graphml, or SNDlib .txt)")
