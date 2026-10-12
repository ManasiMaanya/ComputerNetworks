"""Phase 3-4: recommend a path for SRC -> DST with the trained model; optionally explain it.

    python scripts/infer.py --src R1 --dst R8
    python scripts/infer.py --src R1 --dst R8 --explain          # SHAP + LIME text, JSON, figures
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
from src.config import output_dir, project_dir
from src.features.history import MODEL_UNITS
from src.features.path_features import FEATURE_COLUMNS
from src.routing.recommender import RouteRecommender
from src.xai.explain import explain_recommendation, format_explanation


def safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(name))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", required=True)
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--max-hops", type=int, default=None)
    parser.add_argument("--explain", action="store_true", help="SHAP + LIME explanation, JSON and figures")
    parser.add_argument("--no-lime", action="store_true", help="with --explain: SHAP only")
    parser.add_argument("--no-figures", action="store_true", help="with --explain: skip PNG figures")
    add_common_args(parser)
    args = parser.parse_args()

    cfg, graph, topo = load_context(args)
    recommender = RouteRecommender.load(project_dir(cfg, "models_dir"), cfg)
    banner(f"AI route recommendation {args.src} -> {args.dst}")
    print(f"topology: {rel(topo)}  model: {recommender.schema['model']}  target: {recommender.schema['target']}")
    if recommender.stale_scoring:
        print("warning: config 'scoring' changed since training; predictions follow the old rule. Retrain.")

    rec = recommender.recommend(graph, args.src, args.dst, args.k, args.max_hops)
    print(f"\ncandidates ({len(rec.candidates)}), ranked by predicted cost (lower is better):")
    view = rec.frame.sort_values("rank")[["rank", "path_id", "path", "hops", "sum_delay",
                                          "max_security_risk", "sum_loss", "predicted_cost", "rule_cost"]]
    print(table(view))
    chosen = rec.frame.loc[rec.chosen]
    print(f"\nRECOMMENDED: {' -> '.join(rec.path)}")
    print(f"predicted cost {chosen['predicted_cost']:.4f}   rule cost {chosen['rule_cost']:.4f}")
    print("features: " + ", ".join(f"{c}={chosen[c]:.4g}" for c in FEATURE_COLUMNS))
    print("(one-off query, no traffic history: the current snapshot is treated as steady state)")

    stem = f"{safe(graph.graph.get('name', 'graph'))}_{safe(rec.src)}_{safe(rec.dst)}"
    result = rec.to_dict()
    result["topology"] = rel(topo)
    result["feature_units"] = MODEL_UNITS

    if args.explain:
        banner("explanation (SHAP / LIME)")
        expl = explain_recommendation(rec, recommender, cfg, stem, output_dir(cfg, "explanations"),
                                      output_dir(cfg, "figures"), figures=not args.no_figures,
                                      lime=not args.no_lime)
        for line in format_explanation(expl, cfg["xai"]["top_k"]):
            print(line)
        result["explanation_file"] = rel(Path(expl["files"]["json"]))
        for key, value in expl["files"].items():
            print(f"saved {key}: {rel(Path(value))}")

    route_path = output_dir(cfg, "routes") / f"route_{stem}.json"
    route_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"saved route: {rel(route_path)}")
    return 0


if __name__ == "__main__":
    run(main)
