"""Internet Topology Zoo GML / GraphML -> project graph schema (Phase 7).

Topology Zoo files describe structure (nodes, links, sometimes coordinates and link speeds).
They contain NO delay, loss, congestion, risk, energy, utilization, queue, or reliability
measurements. Mapping (recorded per edge in `metric_source`, see provenance.py):

  bandwidth  documented  LinkSpeedRaw (bps) / 1e6, else LinkSpeed x LinkSpeedUnits, else parsed
                         from the link label ("10 Gbps", "1 GB/s", "OC-192c", "1-2.5 Gb/s" -> lower
                         bound; "B" is read as bits, as the Zoo annotators use it)
             default     topology_zoo.default_bandwidth_mbps when the link has no usable speed
  delay      estimated   great-circle distance / propagation_km_per_ms + per_hop_processing_ms
             default     topology_zoo.default_delay_ms when an endpoint has no coordinates
  others     synthetic   (missing_metric_policy = "synthetic") seeded draws, see _synthetic()
             default     (missing_metric_policy = "default") topology_zoo.defaults values

Parallel links between the same pair are collapsed to the highest-capacity one.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import networkx as nx
import numpy as np

from ..config import load_config
from ..errors import TopologyError
from .load import EDGE_ATTRS, clamp_metric, validate_graph_metrics

UNIT_TO_MBPS = {"": 1e-6, "K": 1e-3, "M": 1.0, "G": 1e3, "T": 1e6}
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def link_bandwidth_mbps(data: dict) -> float | None:
    raw = _number(data.get("LinkSpeedRaw"))
    if raw is not None and raw > 0:
        return raw / 1e6
    speed = _number(data.get("LinkSpeed"))
    unit = str(data.get("LinkSpeedUnits", "")).strip().upper()[:1]
    if speed is not None and speed > 0 and unit in UNIT_TO_MBPS:
        return speed * UNIT_TO_MBPS[unit]
    return parse_speed_label(data.get("LinkLabel") or data.get("label"))


_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-\s*\d+(?:\.\d+)?\s*)?([KMGT])\s*(?:b|bit|bps|B|Byte)", re.I)
_OC = re.compile(r"\bOC-?(\d+)", re.I)
_ETHERNET = {"10GE": 10000.0, "GIGE": 1000.0, "GE": 1000.0, "FE": 100.0}


def parse_speed_label(label) -> float | None:
    """Capacity in Mbps from a free-text Topology Zoo link label, or None if not recognisable."""
    text = str(label or "").strip()
    if not text:
        return None
    match = _OC.search(text)
    if match:
        return int(match.group(1)) * 51.84
    match = _RATE.search(text)
    if match:
        return float(match.group(1)) * UNIT_TO_MBPS[match.group(2).upper()]
    for token, mbps in _ETHERNET.items():
        if re.search(rf"\b{token}\b", text, re.I):
            return mbps
    if re.search(r"\bDS-?3\b", text, re.I):
        return 44.736
    return None


def coordinates(data: dict) -> tuple[float, float] | None:
    lat, lon = _number(data.get("Latitude")), _number(data.get("Longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _synthetic(rng: np.random.Generator) -> dict[str, float]:
    utilization = float(rng.uniform(0.1, 0.85))
    congestion = clamp_metric("congestion", utilization**1.5 + rng.normal(0, 0.05))
    return {
        "utilization": utilization,
        "congestion": congestion,
        "loss": clamp_metric("loss", 0.0005 + 0.05 * congestion**2),
        "queue": float(round(25 * congestion)),
        "security_risk": float(rng.beta(1.5, 5)),
        "energy": 0.8 + 0.4 * utilization,
        "reliability": clamp_metric("reliability", 0.999 - 0.05 * rng.uniform()),
    }


def node_names(raw: nx.Graph) -> dict:
    names, used = {}, set()
    for node, data in sorted(raw.nodes(data=True), key=lambda nd: str(nd[0])):
        base = re.sub(r"\s+", "_", str(data.get("label", node)).strip()) or f"n{node}"
        name = base if base not in used else f"{base}_{node}"
        used.add(name)
        names[node] = name
    return names


def zoo_to_graph(raw: nx.Graph, name: str, zcfg: dict) -> nx.Graph:
    policy = zcfg["missing_metric_policy"]
    if policy not in ("synthetic", "default"):
        raise TopologyError(f"topology_zoo.missing_metric_policy must be 'synthetic' or 'default', got '{policy}'")
    if raw.number_of_nodes() == 0:
        raise TopologyError(f"{name}: GML has no nodes")
    names = node_names(raw)
    graph = nx.Graph(name=name, dataset="Internet Topology Zoo", directed=False)
    for node, data in raw.nodes(data=True):
        coords = coordinates(data)
        graph.add_node(names[node], zoo_id=str(node), label=str(data.get("label", node)),
                       latitude=coords[0] if coords else None, longitude=coords[1] if coords else None,
                       country=data.get("Country"))

    best: dict[frozenset, tuple] = {}
    for u, v, data in raw.edges(data=True):
        if u == v:
            continue
        key = frozenset((names[u], names[v]))
        bw = link_bandwidth_mbps(data)
        count = best[key][2] + 1 if key in best else 1
        if key not in best or (bw or 0) > (best[key][1] or 0):
            best[key] = (data, bw, count)
        else:
            best[key] = (best[key][0], best[key][1], count)

    rng = np.random.default_rng(zcfg["synthetic_seed"])
    for key in sorted(best, key=lambda k: tuple(sorted(k))):
        u, v = sorted(key)
        data, bw, count = best[key]
        source = {}
        if bw is not None:
            attrs, source["bandwidth"] = {"bandwidth": bw}, "documented"
        else:
            attrs, source["bandwidth"] = {"bandwidth": float(zcfg["default_bandwidth_mbps"])}, "default"
        cu, cv = graph.nodes[u], graph.nodes[v]
        if cu["latitude"] is not None and cv["latitude"] is not None:
            km = haversine_km(cu["latitude"], cu["longitude"], cv["latitude"], cv["longitude"])
            attrs["delay"] = km / zcfg["propagation_km_per_ms"] + zcfg["per_hop_processing_ms"]
            attrs["distance_km"] = km
            source["delay"] = "estimated"
        else:
            attrs["delay"], source["delay"] = float(zcfg["default_delay_ms"]), "default"
        synth = _synthetic(rng)  # always drawn so the stream does not depend on policy
        for metric in EDGE_ATTRS:
            if metric in attrs:
                continue
            if policy == "synthetic":
                attrs[metric], source[metric] = synth[metric], "synthetic"
            else:
                attrs[metric], source[metric] = float(zcfg["defaults"][metric]), "default"
        graph.add_edge(u, v, **attrs, metric_source=source, parallel_links=count,
                       link_label=str(data.get("LinkLabel") or data.get("label") or ""))
    validate_graph_metrics(graph, name)
    graph.graph["components"] = nx.number_connected_components(graph)
    graph.graph["source"] = name
    return graph


def load_zoo(path: str | Path, cfg: dict | None = None) -> nx.Graph:
    """Load a Topology Zoo .gml (website export) or .graphml (sk2/topologyzoo sources)."""
    path = Path(path)
    if not path.is_file():
        raise TopologyError(f"Topology Zoo file not found: {path}")
    cfg = cfg or load_config()
    try:
        if path.suffix.lower() == ".graphml":
            raw = nx.read_graphml(path)
        else:
            raw = nx.read_gml(path, label="id")
    except (nx.NetworkXError, ValueError, UnicodeDecodeError, SyntaxError) as exc:
        raise TopologyError(f"{path}: cannot parse {path.suffix} file: {exc}") from exc
    graph = zoo_to_graph(raw, path.stem, cfg["topology_zoo"])
    graph.graph["source"] = str(path)
    return graph
