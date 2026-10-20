"""Phase 2: RIP-like (hop count) and OSPF-like (Dijkstra on configured cost) routes.

    python scripts/baselines.py --src R1 --dst R8
    python scripts/baselines.py --all-pairs          # list pairs where RIP and OSPF differ
"""

from __future__ import annotations

import argparse
import sys
from itertools import permutations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import add_common_args, banner, load_context, rel, run
from src.errors import NoPathError
from src.routing.baselines import ospf_route, rip_route


def trace(result) -> None:
    print(f"{result.method:<5} path: {' -> '.join(result.path)}")
    print(f"{'':<5} hops: {result.hops}   total cost ({result.cost_metric}): {result.cost:g}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src")
    parser.add_argument("--dst")
    parser.add_argument("--ospf-cost", choices=["delay", "inverse_bandwidth"], default=None,
                        help="override config ospf_cost")
    parser.add_argument("--all-pairs", action="store_true", help="run every ordered pair")
    add_common_args(parser)
    args = parser.parse_args()
    if not args.all_pairs and not (args.src and args.dst):
        parser.error("give --src and --dst, or --all-pairs")

    cfg, graph, topo = load_context(args)
    strategy = args.ospf_cost or cfg["ospf_cost"]
    ref = float(cfg["ospf_reference_bandwidth_bps"])
    banner("Phase 2: RIP-like vs OSPF-like")
    print(f"topology: {rel(topo)}  ospf_cost={strategy}")

    pairs = list(permutations(sorted(graph.nodes()), 2)) if args.all_pairs else [(args.src, args.dst)]
    differ = 0
    for src, dst in pairs:
        try:
            rip = rip_route(graph, src, dst)
            ospf = ospf_route(graph, src, dst, strategy, ref)
        except NoPathError as exc:
            print(f"\n{src} -> {dst}: no path ({exc})")
            continue
        same = rip.path == ospf.path
        differ += not same
        if args.all_pairs and same:
            continue
        print(f"\n{src} -> {dst}" + ("" if same else "   [RIP and OSPF differ]"))
        trace(rip)
        trace(ospf)
    if args.all_pairs:
        print(f"\npairs where RIP and OSPF paths differ: {differ} of {len(pairs)}")
    return 0


if __name__ == "__main__":
    run(main)
