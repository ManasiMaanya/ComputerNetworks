"""Load the sample topology and print node/edge counts (Phase 0)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.topology.load import load_graph


def main() -> int:
    config_path = ROOT / "configs" / "default.json"
    if not config_path.is_file():
        print(f"error: missing config {config_path}", file=sys.stderr)
        return 1
    config = json.loads(config_path.read_text(encoding="utf-8"))
    topo = ROOT / config.get("sample_topology", "data/samples/sample_topology.json")
    if not topo.is_file():
        print(f"error: missing topology {topo}", file=sys.stderr)
        return 1
    graph = load_graph(topo)
    print(f"topology: {topo.relative_to(ROOT)}")
    print(f"nodes: {graph.number_of_nodes()}")
    print(f"edges: {graph.number_of_edges()}")
    print("nodes:", ", ".join(str(n) for n in graph.nodes()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
