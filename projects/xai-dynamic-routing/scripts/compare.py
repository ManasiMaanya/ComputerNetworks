"""Phase 5: RIP-like vs OSPF-like vs AI on the same graph snapshot, several pairs.

    python scripts/compare.py                              # sample topology, pairs from config
    python scripts/compare.py --all-pairs
    python scripts/compare.py --topology data/raw/Abilene.gml --random-pairs 15
    python scripts/compare.py --pairs R1:R8,R2:R3

Writes outputs/reports/compare_<topology>.csv and .md, and outputs/figures/compare_<topology>.png.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import add_common_args, banner, load_context, rel, run, table
from src.errors import ModelError
from src.config import output_dir, project_dir, resolve_path
from src.evaluate.compare import (
    choose_pairs,
    comparison_figure,
    head_to_head,
    markdown_report,
    run_comparison,
    summarize,
)
from src.routing.recommender import RouteRecommender
from src.topology.provenance import provenance_summary


def parse_pairs(text: str):
    pairs = []
    for item in text.split(","):
        if ":" not in item:
            raise SystemExit(f"error: bad pair '{item}', expected SRC:DST")
        a, b = item.split(":", 1)
        pairs.append((a.strip(), b.strip()))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairs", default=None, help="comma list SRC:DST,...")
    parser.add_argument("--all-pairs", action="store_true")
    parser.add_argument("--random-pairs", type=int, default=None, help="seeded random ordered pairs")
    parser.add_argument("--ospf-cost", choices=["delay", "inverse_bandwidth"], default=None,
                        help="override config ospf_cost (e.g. inverse_bandwidth when delays are defaults)")
    add_common_args(parser)
    args = parser.parse_args()

    cfg, graph, topo = load_context(args)
    if args.ospf_cost:
        cfg["ospf_cost"] = args.ospf_cost
    recommender = RouteRecommender.load(project_dir(cfg, "models_dir"), cfg)
    try:
        blackbox = RouteRecommender.load(project_dir(cfg, "models_dir"), cfg, blackbox=True)
    except ModelError:
        blackbox = None
    name = graph.graph.get("name", topo.stem)
    is_sample = topo.resolve() == resolve_path(cfg["sample_topology"])
    pairs = choose_pairs(graph, cfg, explicit=parse_pairs(args.pairs) if args.pairs else None,
                         all_pairs=args.all_pairs, random_pairs=args.random_pairs, is_sample=is_sample)

    banner(f"Phase 5: RIP vs OSPF vs AI on {name}")
    print(f"topology: {rel(topo)}  nodes={graph.number_of_nodes()} edges={graph.number_of_edges()} "
          f"components={graph.graph.get('components')}  ospf_cost={cfg['ospf_cost']}  pairs={len(pairs)}")
    prov = provenance_summary(graph)
    if prov:
        print("metric provenance (edges): " + "; ".join(
            f"{m}: " + ", ".join(f"{k}={v}" for k, v in counts.items()) for m, counts in prov.items()))
    if recommender.stale_scoring:
        print("warning: config 'scoring' changed since training; retrain for consistent AI routes")
    if blackbox is None:
        print("note: no black-box model in models/ (AI-BB column skipped); rerun scripts/train.py")

    frame = run_comparison(graph, pairs, cfg, recommender, name, blackbox)
    for (src, dst), group in frame.groupby(["src", "dst"], sort=False):
        print(f"\n{src} -> {dst}")
        for row in group.itertuples(index=False):
            if row.status != "ok":
                print(f"  {row.method:<5} {row.status}: {row.note}")
                continue
            print(f"  {row.method:<5} {row.path:<40} hops={row.hops:<2} delay={row.sum_delay:<8.4g} "
                  f"loss={row.sum_loss:<7.4g} max_risk={row.max_security_risk:<6.3g} "
                  f"cost({row.route_cost_metric})={row.route_cost:.4g}")
            if row.method == "AI":
                print(f"        why: {row.note}")

    summary = summarize(frame)
    h2h = head_to_head(frame)
    banner("summary")
    if summary.empty:
        print("no pair had paths for every method")
    else:
        print(table(summary))
    for base, stats in h2h.items():
        print(f"AI vs {base}: different path in {stats['different_path']}/{stats['pairs']} pairs; "
              f"AI lower risk {stats['ai_lower_max_security_risk']}, higher risk {stats['ai_higher_max_security_risk']}; "
              f"AI lower delay {stats['ai_lower_sum_delay']}, higher delay {stats['ai_higher_sum_delay']}")
    failed = frame[frame["status"] != "ok"]
    print(f"failed/no-path rows: {len(failed)}")

    stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    if args.ospf_cost:
        stem += f"_ospf-{args.ospf_cost}"
    reports = output_dir(cfg, "reports")
    csv_path, md_path = reports / f"compare_{stem}.csv", reports / f"compare_{stem}.md"
    fig_path = output_dir(cfg, "figures") / f"compare_{stem}.png"
    meta = {"topology": name, "file": rel(topo), "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(), "ospf_cost": cfg["ospf_cost"],
            "k_candidate_paths": cfg["k_candidate_paths"], "max_hops": cfg["max_hops"],
            "model_scoring_fingerprint": recommender.schema["scoring_fingerprint"], "pairs": len(pairs)}
    if prov:
        meta["metric_provenance"] = json.dumps(prov)
    frame.to_csv(csv_path, index=False)
    md_path.write_text(markdown_report(frame, summary, h2h, meta), encoding="utf-8")
    comparison_figure(frame, fig_path, f"RIP vs OSPF-like vs AI - {name}")
    for path in (csv_path, md_path, fig_path):
        print(f"saved: {rel(path)}")
    return 0


if __name__ == "__main__":
    run(main)
