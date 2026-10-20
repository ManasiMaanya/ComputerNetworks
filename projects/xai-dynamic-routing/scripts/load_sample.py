"""Load the sample topology and print node/edge counts (Phase 0)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import rel, run
from src.config import load_config, resolve_path
from src.topology.load import load_graph


def main() -> int:
    config = load_config()
    topo = resolve_path(config["sample_topology"])
    graph = load_graph(topo)
    print(f"topology: {rel(topo)}")
    print(f"nodes: {graph.number_of_nodes()}")
    print(f"edges: {graph.number_of_edges()}")
    print("nodes:", ", ".join(str(n) for n in graph.nodes()))
    print(f"connected components: {graph.graph['components']}")
    return 0


if __name__ == "__main__":
    run(main)
