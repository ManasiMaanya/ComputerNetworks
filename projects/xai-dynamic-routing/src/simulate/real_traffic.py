"""Real-data counterpart to traffic.py: steps a graph's load-dependent metrics from an ordered
sequence of real SNDlib demand matrices (src/topology/sndlib.py::load_demand_matrix) instead of
the synthetic mean-reverting model -- e.g. SNDlib's Abilene 5-minute traffic matrices.

For each snapshot:
  1. Every directed demand (src, dst) with non-zero traffic is routed along its OSPF(delay)
     shortest path over the static topology (src/routing/baselines.py::ospf_route) -- the same
     physical routes a real IGP would compute from the topology's own delay numbers. Both
     directions of a pair add their Mbit/s load onto the same undirected edge, since the
     topology itself is undirected.
  2. Per edge: utilization = clip(load_mbps / bandwidth_mbps), congestion = clip(utilization**1.5),
     loss = clip(0.0005 + 0.05*congestion**2), queue = round(25*congestion) -- the SAME formulas
     src/topology/zoo.py uses to synthesize these metrics when a topology has no real
     measurements (src/topology/zoo.py::_synthetic), reused here rather than invented, with one
     deliberate difference: no noise term is added to congestion, since the real traffic matrix
     already supplies real variation step to step.
  3. delay, bandwidth, reliability, energy, and security_risk are left at the topology's existing
     values: the demand data carries no signal for any of them.

Every edge's utilization/congestion/loss/queue is recomputed from that snapshot's routed load
alone (an edge with zero routed demand gets congestion 0, not a leftover synthetic placeholder),
so metrics never mix real and synthetic signal within one snapshot.

A demand pair absent from a matrix is real-measured zero traffic (SNDlib drops near-zero demands
rather than writing them as 0.0), not missing data, and is treated as such.
"""

from __future__ import annotations

import io
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from ..errors import TopologyError
from ..routing.baselines import ospf_route_from_config
from ..topology.load import clamp_metric
from ..topology.sndlib import load_demand_matrix

#: Edge metrics apply_real_traffic() derives from routed real load; every other metric is static.
REAL_METRICS = ("utilization", "congestion", "loss", "queue")
#: Matches e.g. demandMatrix-abilene-zhang-5min-20040301-0000.txt, wherever it sits in an archive.
MATRIX_NAME = re.compile(r"^demandMatrix-.*\.txt$")


def edge_load(graph: nx.Graph, demands: dict[tuple[str, str], float], cfg: dict) -> dict[tuple[str, str], float]:
    """Mbit/s load on every undirected edge of `graph` from routing each directed demand along
    its OSPF(delay) shortest path. Edge keys are sorted tuples (u, v) with u < v; an edge with no
    routed load is simply absent (callers should default a missing key to 0.0)."""
    load: dict[tuple[str, str], float] = {}
    for (src, dst), value in demands.items():
        if value <= 0:
            continue
        route = ospf_route_from_config(graph, src, dst, cfg)
        for u, v in zip(route.path, route.path[1:]):
            key = tuple(sorted((u, v)))
            load[key] = load.get(key, 0.0) + value
    return load


def apply_real_traffic(graph: nx.Graph, demands: dict[tuple[str, str], float], cfg: dict) -> nx.Graph:
    """Copy of `graph` with utilization/congestion/loss/queue set from routing `demands` (see
    module docstring); every other metric is left untouched. `graph` itself is not modified."""
    updated = graph.copy()
    load = edge_load(graph, demands, cfg)
    for u, v, data in updated.edges(data=True):
        mbps = load.get(tuple(sorted((u, v))), 0.0)
        utilization = clamp_metric("utilization", mbps / data["bandwidth"])
        congestion = clamp_metric("congestion", utilization ** 1.5)
        data["utilization"] = utilization
        data["congestion"] = congestion
        data["loss"] = clamp_metric("loss", 0.0005 + 0.05 * congestion ** 2)
        data["queue"] = float(round(25 * congestion))
    return updated


@dataclass(frozen=True)
class RealTrace:
    graphs: list[nx.Graph]
    timestamps: list[str | None]  # DemandMatrix.timestamp from each file, same order


def real_trace(base_graph: nx.Graph, matrix_paths: list[Path], cfg: dict) -> RealTrace:
    """One snapshot per path in `matrix_paths`, in the order given -- sort the paths first (SNDlib
    names dynamic-traffic files so lexical order is chronological order) for a meaningful series.
    `base_graph` is not modified; each returned graph is an independent copy."""
    nodes = set(map(str, base_graph.nodes()))
    graphs, timestamps = [], []
    for path in matrix_paths:
        matrix = load_demand_matrix(path, nodes)
        graphs.append(apply_real_traffic(base_graph, matrix.demands, cfg))
        timestamps.append(matrix.timestamp)
    return RealTrace(graphs=graphs, timestamps=timestamps)


def discover_matrix_files(directory: str | Path) -> list[Path]:
    """Every `*.txt` file directly in `directory`, sorted (SNDlib's own dynamic-traffic archives
    name files so lexical order is chronological order, e.g. ...-20040301-0000.txt before
    ...-20040301-0005.txt)."""
    directory = Path(directory)
    if not directory.is_dir():
        raise TopologyError(f"real-traffic directory not found: {directory}")
    paths = sorted(directory.glob("*.txt"))
    if not paths:
        raise TopologyError(f"{directory}: no *.txt demand-matrix files found")
    return paths


def extract_matrix_files(archive_bytes: bytes, dest_dir: str | Path, limit: int | None) -> list[Path]:
    """Every demandMatrix-*.txt member of a gzipped tar archive (an SNDlib dynamic-traffic
    download, e.g. directed-abilene-zhang-5min-over-6months-ALL-native.tgz), flattened into
    `dest_dir` regardless of whatever subdirectory the archive nests them under. Kept in
    chronological (lexical filename) order; `limit` (None or < 0 means "all") keeps only the
    chronologically-first `limit` files -- the rest are never extracted."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        members = sorted((m for m in tar.getmembers() if m.isfile() and MATRIX_NAME.match(Path(m.name).name)),
                         key=lambda m: Path(m.name).name)
        if limit is not None and limit >= 0:
            members = members[:limit]
        written = []
        for member in members:
            target = dest_dir / Path(member.name).name
            target.write_bytes(tar.extractfile(member).read())
            written.append(target)
    return written
