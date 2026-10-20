"""Explanation-quality evaluation: fidelity, SHAP/LIME agreement, seed stability, latency.

    python scripts/explain_quality.py
    python scripts/explain_quality.py --pairs R1:R8,R2:R7 --no-lime
    python scripts/explain_quality.py --model-seeds 3 --table data/processed/training_table.csv

Writes outputs/reports/explanation_quality.json, .md and outputs/figures/explanation_quality.png.
With --model-seeds > 1 the forest is retrained with each seed on the same table (no CV) and
SHAP vectors are compared for the same queries. Use --table to reuse a saved training table;
otherwise it is rebuilt with the current config (or a reduced budget with --quick).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.cli import add_common_args, banner, load_context, rel, run  # noqa: E402
from src.config import output_dir, project_dir, resolve_input_path  # noqa: E402
from src.errors import ConfigError  # noqa: E402
from src.evaluate.explanation_quality import (  # noqa: E402
    model_seed_stability,
    quality_figure,
    quality_markdown,
    quality_report,
)
from src.features.history import MODEL_COLUMNS  # noqa: E402
from src.routing.dataset import build_training_table  # noqa: E402
from src.routing.recommender import RouteRecommender  # noqa: E402

QUICK_TRAINING = {
    "sample_snapshots": 30,
    "synthetic_graphs": 20,
    "trace_steps": 120,
    "synthetic_trace_steps": 16,
    "n_estimators": 80,
}


def parse_pairs(text: str):
    pairs = []
    for item in text.split(","):
        if ":" not in item:
            raise SystemExit(f"error: bad pair '{item}', expected SRC:DST")
        src, dst = item.split(":", 1)
        pairs.append((src.strip(), dst.strip()))
    return pairs


def load_or_build_table(path, cfg: dict, graph, quick: bool):
    if path:
        path = resolve_input_path(path)
        if not path.is_file():
            raise ConfigError(f"training table not found: {path}")
        table = pd.read_csv(path)
        required = (*MODEL_COLUMNS, "target", "family", "group")
        missing = [column for column in required if column not in table]
        if missing:
            raise ConfigError(f"{path}: missing columns {missing}")
        return table, path
    train_cfg = dict(cfg["training"])
    if quick:
        train_cfg.update(QUICK_TRAINING)
        cfg = {**cfg, "training": train_cfg}
    table = build_training_table(graph, cfg)
    return table, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairs", default=None, help="comma list SRC:DST,... (default: config compare.pairs)")
    parser.add_argument("--repeats", type=int, default=None, help="SHAP timing repeats (default: evaluation.explanation.repeats)")
    parser.add_argument("--lime-seeds", type=int, default=None, help="number of LIME sampling seeds (default: config)")
    parser.add_argument("--model-seeds", type=int, default=None, help="forest retraining seeds; 0 disables (default: config)")
    parser.add_argument("--top-k", type=int, default=None, help="top-k features for overlap/fidelity (default: config)")
    parser.add_argument("--no-lime", action="store_true")
    parser.add_argument("--table", default=None, help="reuse a processed training_table.csv for seed stability")
    parser.add_argument("--quick", action="store_true", help="smaller training budget when a table must be rebuilt")
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--out", default=None, help="JSON report path (default: outputs/reports/explanation_quality.json)")
    add_common_args(parser)
    args = parser.parse_args()

    cfg, graph, topo = load_context(args)
    ecfg = cfg["evaluation"]["explanation"]
    repeats = args.repeats if args.repeats is not None else ecfg["repeats"]
    model_seeds = args.model_seeds if args.model_seeds is not None else ecfg["model_seeds"]
    lime_count = args.lime_seeds if args.lime_seeds is not None else ecfg["lime_seeds"]
    top_k = args.top_k if args.top_k is not None else ecfg["top_k"]
    base_seed = int(cfg["xai"]["seed"])
    lime_seeds = [base_seed + i for i in range(max(0, lime_count))]
    include_lime = not args.no_lime and bool(lime_seeds)
    pairs = parse_pairs(args.pairs) if args.pairs else [tuple(pair) for pair in cfg["compare"]["pairs"]]
    recommender = RouteRecommender.load(project_dir(cfg, "models_dir"), cfg)

    banner("Explanation quality")
    print(f"topology: {rel(topo)}  pairs={len(pairs)}  top_k={top_k}  "
          f"SHAP repeats={repeats}  LIME seeds={lime_seeds if include_lime else 'disabled'}")
    if recommender.stale_scoring:
        print("warning: config 'scoring' changed since training; explanations describe the loaded model")
    report = quality_report(recommender, cfg, graph, pairs, repeats=repeats,
                            lime_seeds=lime_seeds or [None], top_k=top_k,
                            include_lime=include_lime)

    if model_seeds and model_seeds > 1:
        banner(f"Random Forest seed stability ({model_seeds} seeds)")
        table, table_path = load_or_build_table(args.table, cfg, graph, args.quick)
        seeds = [int(cfg["training"]["seed"]) + i for i in range(model_seeds)]
        stability = model_seed_stability(graph, table, cfg, pairs, seeds, top_k=top_k,
                                         reference_recommender=recommender)
        report["model_seed_stability"] = stability
        report["stability_table"] = rel(table_path) if table_path else "rebuilt from config"
        print(f"table: {report['stability_table']}  seeds={seeds}")
        print(f"path agreement {stability['summary'].get('path_agreement_rate')}; "
              f"mean SHAP Spearman {stability['summary'].get('mean_spearman')}")
        report["summary"]["model_seed_spearman"] = stability["summary"].get("mean_spearman")
        report["summary"]["model_seed_path_agreement"] = stability["summary"].get("path_agreement_rate")
        report["summary"]["model_seed_reference_agreement"] = stability["summary"].get("reference_agreement_rate")

    reports = output_dir(cfg, "reports")
    json_path = Path(args.out) if args.out else reports / "explanation_quality.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = json_path.with_suffix(".md")
    md_path.write_text(quality_markdown(report), encoding="utf-8")
    saved = [json_path, md_path]
    if not args.no_figures:
        figure = output_dir(cfg, "figures") / "explanation_quality.png"
        quality_figure(report, figure)
        saved.append(figure)

    summary = report["summary"]
    banner("summary")
    for key in ("shap_fidelity_spearman", "shap_lime_spearman", "lime_seed_spearman",
                "model_seed_spearman", "shap_latency_ms_median", "lime_latency_ms_median"):
        if key in summary:
            value = summary[key]
            print(f"  {key:<34} {'n/a' if value is None else f'{value:.4f}'}")
    total = len(report["per_pair"])
    print(f"pairs evaluated: {summary['pairs']}/{total}  failed: {total - summary['pairs']}")
    for path in saved:
        print(f"saved: {rel(path)}")
    return 0


if __name__ == "__main__":
    run(main)
