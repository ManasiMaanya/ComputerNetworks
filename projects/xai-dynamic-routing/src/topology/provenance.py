"""Per-edge metric provenance for imported topologies.

Edges from Topology Zoo / SNDlib carry `metric_source = {metric: kind}` where kind is one of:
  documented  value taken from the dataset file (e.g. LinkSpeedRaw, SNDlib capacity)
  estimated   derived from dataset fields by a stated formula (e.g. delay from coordinates)
  synthetic   seeded pseudo-random draw (no measurement exists in the dataset)
  default     fixed configured default (no measurement exists in the dataset)
Hand-written project JSON topologies have no `metric_source` and are treated as given.
"""

from __future__ import annotations

from collections import Counter

import networkx as nx

from .load import EDGE_ATTRS

KINDS = ("documented", "estimated", "synthetic", "default")


def provenance_summary(graph: nx.Graph) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter] = {m: Counter() for m in EDGE_ATTRS}
    found = False
    for _, _, data in graph.edges(data=True):
        source = data.get("metric_source")
        if not isinstance(source, dict):
            continue
        found = True
        for metric in EDGE_ATTRS:
            counts[metric][source.get(metric, "unknown")] += 1
    return {m: dict(c) for m, c in counts.items()} if found else {}
