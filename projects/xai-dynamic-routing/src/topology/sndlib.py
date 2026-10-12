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
"""

from __future__ import annotations

import re
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
