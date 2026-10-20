"""SNDlib native-format (.txt) network + demands -> project graph schema (Phase 7).

Reads the NODES, LINKS, and DEMANDS sections of an SNDlib "native" file:
    NODES ( <name> ( <x> <y> ) ... )
    LINKS ( <id> ( <src> <dst> ) <pre_cap> <pre_cap_cost> <routing_cost> <setup_cost> ( <cap> <cost> ... ) ... )
    DEMANDS ( <id> ( <src> <dst> ) <routing_unit> <demand_value> <max_path_length> ... )

bandwidth: pre-installed capacity if > 0, else the largest module capacity ("documented",
in the instance's capacity units, treated as Mbps). delay: from coordinates when they are valid
longitude/latitude ("estimated", same formula as Topology Zoo), else the default. All other
metrics follow topology_zoo.missing_metric_policy. Demands are kept in graph.graph["demands"]
(largest first) and used as comparison pairs.

`load_demand_matrix` reads the other SNDlib file shape: a real-traffic snapshot from one of
SNDlib's time-varying "dynamic traffic" archives (e.g. Abilene's 5-minute matrices) -- one file
per time interval, sharing the base network's NODES but with an empty `LINKS ( )` section and a
DEMANDS section listing only the demand pairs with non-negligible traffic that interval (SNDlib's
own convention rounds and drops near-zero demands, below 0.0000005 Mbit/s, from the file entirely
rather than writing them as 0.0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from ..config import load_config
from ..errors import TopologyError
from .zoo import zoo_to_graph

_SECTION = r"{name}\s*\((.*?)\n\s*\)"
_NODE = re.compile(r"^\s*(\S+)\s*\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)", re.M)
_LINK = re.compile(r"^\s*(\S+)\s*\(\s*(\S+)\s+(\S+)\s*\)\s*([-\d.eE+]+)\s+[-\d.eE+]+\s+[-\d.eE+]+\s+"
                   r"[-\d.eE+]+\s*\(([^)]*)\)", re.M)
_DEMAND = re.compile(r"^\s*(\S+)\s*\(\s*(\S+)\s+(\S+)\s*\)\s*[-\d.eE+]+\s+([-\d.eE+]+)", re.M)
_META_LINE = re.compile(r"^\s*(\w+)\s*=\s*(.+?)\s*$", re.M)


def _section(text: str, name: str, path: Path, required: bool = True) -> str:
    match = re.search(_SECTION.format(name=name), text, re.S)
    if not match:
        if required:
            raise TopologyError(f"{path}: SNDlib section '{name}' not found")
        return ""
    return match.group(1)


def load_sndlib(path: str | Path, cfg: dict | None = None) -> nx.Graph:
    path = Path(path)
    if not path.is_file():
        raise TopologyError(f"SNDlib file not found: {path}")
    cfg = cfg or load_config()
    text = re.sub(r"#.*", "", path.read_text(encoding="utf-8", errors="replace"))

    raw = nx.MultiGraph()
    for name, x, y in _NODE.findall(_section(text, "NODES", path)):
        raw.add_node(name, label=name, Longitude=float(x), Latitude=float(y))
    if raw.number_of_nodes() == 0:
        raise TopologyError(f"{path}: NODES section has no nodes")

    links = _LINK.findall(_section(text, "LINKS", path))
    if not links:
        raise TopologyError(f"{path}: LINKS section has no parsable links")
    for link_id, u, v, pre_cap, modules in links:
        for endpoint in (u, v):
            if endpoint not in raw:
                raise TopologyError(f"{path}: link {link_id} uses unknown node '{endpoint}'")
        numbers = [float(n) for n in modules.split()]
        module_caps = numbers[0::2]
        capacity = float(pre_cap) if float(pre_cap) > 0 else max(module_caps, default=0.0)
        attrs = {"LinkLabel": link_id}
        if capacity > 0:
            attrs["LinkSpeedRaw"] = capacity * 1e6  # capacity units treated as Mbps
        raw.add_edge(u, v, **attrs)

    demands = []
    for demand_id, u, v, value in _DEMAND.findall(_section(text, "DEMANDS", path, required=False)):
        if u in raw and v in raw and u != v:
            demands.append({"id": demand_id, "src": u, "dst": v, "value": float(value)})
    demands.sort(key=lambda d: -d["value"])

    graph = zoo_to_graph(raw, path.stem, cfg["topology_zoo"])
    graph.graph.update({"dataset": "SNDlib (native format)", "source": str(path), "demands": demands})
    return graph


@dataclass(frozen=True)
class DemandMatrix:
    """One SNDlib real-traffic snapshot: `demands[(src, dst)]` is that directed pair's measured
    load in Mbit/s. A pair absent from `demands` carried zero (real-measured, not missing) traffic
    that interval -- callers should treat a missing key as 0.0, not as an error."""

    timestamp: str | None
    demands: dict[tuple[str, str], float]


def load_demand_matrix(path: str | Path, nodes: set[str]) -> DemandMatrix:
    """Parse one SNDlib dynamic-traffic-matrix file against a known node set (normally the base
    network's `graph.nodes()`, loaded separately via `load_sndlib`). Unlike `load_sndlib`, the
    LINKS section here is expected to be empty -- these files carry no topology, only traffic."""
    path = Path(path)
    if not path.is_file():
        raise TopologyError(f"SNDlib demand-matrix file not found: {path}")
    text = re.sub(r"#.*", "", path.read_text(encoding="utf-8", errors="replace"))

    meta = {key: value for key, value in _META_LINE.findall(_section(text, "META", path, required=False))}
    unit = meta.get("unit")
    if unit is not None and unit != "MBITPERSEC":
        raise TopologyError(f"{path}: demand unit '{unit}' is not MBITPERSEC, the only unit this "
                            f"loader converts (no conversion applied) -- check the source data")

    demands: dict[tuple[str, str], float] = {}
    for demand_id, u, v, value in _DEMAND.findall(_section(text, "DEMANDS", path, required=False)):
        if u not in nodes or v not in nodes:
            raise TopologyError(f"{path}: demand {demand_id} uses unknown node(s) '{u}'/'{v}'")
        if u == v:
            raise TopologyError(f"{path}: demand {demand_id} has identical source and destination '{u}'")
        demands[(u, v)] = float(value)
    return DemandMatrix(timestamp=meta.get("time"), demands=demands)
