"""Phase 1: print k candidate paths and their feature vectors for SRC -> DST.

    python scripts/features.py --src R1 --dst R8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import add_common_args, banner, load_context, rel, run, table
from src.features.path_features import FEATURE_COLUMNS, FEATURE_UNITS, candidates_frame, enumerate_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", required=True)
    parser.add_argument("--k", type=int, default=None, help="override k_candidate_paths")
    parser.add_argument("--max-hops", type=int, default=None, help="override max_hops")
    parser.add_argument("--strategy", choices=["hops", "delay", "mixed"], default=None,
                        help="override candidate_strategy")
    parser.add_argument("--csv", default=None, help="also write the feature table to this CSV path")
    add_common_args(parser)
    args = parser.parse_args()

    cfg, graph, topo = load_context(args)
    k = args.k or cfg["k_candidate_paths"]
    max_hops = args.max_hops or cfg["max_hops"]
    strategy = args.strategy or cfg["candidate_strategy"]
    banner(f"Phase 1: candidate paths {args.src} -> {args.dst}")
    print(f"topology: {rel(topo)}  nodes={graph.number_of_nodes()} edges={graph.number_of_edges()}")
    print(f"k={k}  max_hops={max_hops}  candidate_strategy={strategy} (Yen k-shortest; see docs/xai-dynamic-routing-methods.md)")

    candidates = enumerate_candidates(graph, args.src, args.dst, k, max_hops, strategy)
    frame = candidates_frame(candidates, args.src, args.dst)
    print(f"\ncandidates found: {len(candidates)}")
    print(table(frame[["path_id", "path"]]))
    print("\nfeature vectors (columns in canonical order):")
    print(table(frame[["path_id", *FEATURE_COLUMNS]]))
    print("\nunits: " + ", ".join(f"{c}={FEATURE_UNITS[c]}" for c in FEATURE_COLUMNS))
    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(out, index=False)
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    run(main)
