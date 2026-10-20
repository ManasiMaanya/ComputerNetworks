"""Label sensitivity: retrain under alternative cost weights and compare rule vs model response.

    python scripts/label_sensitivity.py --quick
    python scripts/label_sensitivity.py --scenarios baseline,delay_heavy,risk_heavy --random-weight-draws 0
    python scripts/label_sensitivity.py --scenarios baseline,risk_heavy --cv

Writes outputs/reports/label_sensitivity.json, .md and outputs/figures/label_sensitivity.png.
Each scenario regenerates labels with that scenario's weights and retrains the forest, so the
runtime is roughly (number of scenarios) x one training run. `--quick` reduces the data budget;
use the default full config for reported numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import add_common_args, banner, load_context, rel, run  # noqa: E402
from src.config import output_dir  # noqa: E402
from src.evaluate.label_sensitivity import (  # noqa: E402
    label_sensitivity_figure,
    label_sensitivity_markdown,
    study_label_sensitivity,
    weight_scenarios,
)

QUICK_TRAINING = {
    "sample_snapshots": 30,
    "synthetic_graphs": 20,
    "trace_steps": 100,
    "synthetic_trace_steps": 16,
    "n_estimators": 80,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenarios", default=None,
                        help="comma list of scenario names (default: all built-in + random draws)")
    parser.add_argument("--random-weight-draws", type=int, default=None,
                        help="seeded Dirichlet weight draws (default: config)")
    parser.add_argument("--seed", type=int, default=None, help="random-weight seed (default: config)")
    parser.add_argument("--quick", action="store_true", help="smaller training budget for exploration")
    parser.add_argument("--cv", action="store_true", help="also run group K-fold CV per scenario (slower)")
    parser.add_argument("--blackbox", action="store_true", help="also train the MLP baseline")
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--out", default=None, help="JSON report path (default: outputs/reports/label_sensitivity.json)")
    add_common_args(parser)
    args = parser.parse_args()

    cfg, graph, topo = load_context(args)
    lcfg = cfg["evaluation"]["label_sensitivity"]
    draws = args.random_weight_draws if args.random_weight_draws is not None else lcfg["random_weight_draws"]
    seed = args.seed if args.seed is not None else lcfg["seed"]
    all_scenarios = weight_scenarios(cfg["scoring"], random_draws=draws, seed=seed)
    if args.scenarios:
        names = [name.strip() for name in args.scenarios.split(",") if name.strip()]
        unknown = [name for name in names if name not in all_scenarios]
        if unknown:
            raise SystemExit(f"error: unknown scenario(s) {unknown}; choose from {sorted(all_scenarios)}")
        selected = {name: all_scenarios[name] for name in names}
        if "baseline" not in selected:
            selected = {"baseline": all_scenarios["baseline"], **selected}
    else:
        selected = all_scenarios

    if args.quick:
        cfg["training"].update(QUICK_TRAINING)
        if cfg["training"]["labels"] == "rule_snapshot":
            cfg["training"]["sample_snapshots"] = 30

    banner("Label sensitivity")
    print(f"topology: {rel(topo)}  labels={cfg['training']['labels']}  scenarios={len(selected)}  "
          f"seed={cfg['training']['seed']}  quick={args.quick}  cv={args.cv}")
    for name, scoring in selected.items():
        weights = ", ".join(f"{term}={scoring['weights'].get(term, 0.0):.3f}" for term in scoring["weights"])
        print(f"  {name:<22} {weights}")

    report = study_label_sensitivity(graph, cfg, scenarios=selected,
                                     include_blackbox=args.blackbox, cv=args.cv)

    reports = output_dir(cfg, "reports")
    json_path = Path(args.out) if args.out else reports / "label_sensitivity.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = json_path.with_suffix(".md")
    md_path.write_text(label_sensitivity_markdown(report), encoding="utf-8")
    saved = [json_path, md_path]
    if not args.no_figures:
        figure = output_dir(cfg, "figures") / "label_sensitivity.png"
        label_sensitivity_figure(report, figure)
        saved.append(figure)

    summary = report["summary"]
    banner("summary")
    for key in ("mean_rule_change_rate", "mean_model_change_rate", "rule_model_change_correlation",
                "mean_retrained_top1", "mean_transfer_top1", "transfer_gap"):
        value = summary.get(key)
        print(f"  {key:<32} {'n/a' if value is None else f'{value:.4f}'}")
    for name, row in report["scenarios"].items():
        if name == report["baseline"]:
            continue
        rule = row["rule_vs_baseline"]["change_rate"]
        model = row["model_vs_baseline"]["change_rate"]
        print(f"  {name:<22} rule change {rule if rule is None else f'{rule:.3f}'}  "
              f"model change {model if model is None else f'{model:.3f}'}  "
              f"retrained top-1 {row['model_top1']:.3f}  transfer {row['transfer_from_baseline']['top1']:.3f}")
    for path in saved:
        print(f"saved: {rel(path)}")
    return 0


if __name__ == "__main__":
    run(main)
