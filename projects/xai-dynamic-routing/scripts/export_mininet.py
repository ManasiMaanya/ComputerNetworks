"""Phase 7 (secondary): write a Mininet script for a topology and syntax-check it.

    python scripts/export_mininet.py                         # sample topology
    python scripts/export_mininet.py --topology data/raw/Abilene.graphml

Output: outputs/mininet/<topology>_mininet.py. Running it needs Linux + Mininet + sudo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import add_common_args, banner, load_context, rel, run
from src.config import output_dir
from src.simulate.mininet_export import TCLINK_MAX_MBPS, mininet_script


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    args = parser.parse_args()
    cfg, graph, topo = load_context(args)
    name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in graph.graph.get("name", topo.stem))
    target = output_dir(cfg, "mininet") / f"{name}_mininet.py"
    text, stats = mininet_script(graph, rel(topo), target.name)
    target.write_text(text, encoding="utf-8")
    compile(text, str(target), "exec")  # syntax check without writing a .pyc

    banner("Mininet export")
    print(f"topology: {rel(topo)}  routers={stats['routers']} links={stats['links']}")
    if stats["bandwidth_capped"]:
        print(f"note: {stats['bandwidth_capped']} links capped at {TCLINK_MAX_MBPS:g} Mbps (TCLink limit)")
    print(f"saved: {rel(target)} (syntax OK; not executed here - needs Linux, Mininet, sudo)")
    print(f"run on Linux: sudo python3 {target.name} --cli")
    return 0


if __name__ == "__main__":
    run(main)
