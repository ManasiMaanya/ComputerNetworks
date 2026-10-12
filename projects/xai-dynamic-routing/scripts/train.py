"""Phase 3: build the labeled candidate-path table, train the Random Forest and the black-box MLP,
evaluate both on held-out pairs (and, with future_outcome labels, a held-out later time period).

    python scripts/train.py

Writes models/route_cost_rf.joblib, models/route_cost_mlp.joblib, models/feature_schema.json,
models/training_report.json, models/xai_background.csv, and data/processed/training_table.csv.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import add_common_args, banner, load_context, rel, run
from src.config import project_dir
from src.routing.dataset import build_training_table, split_groups
from src.routing.recommender import save_artifacts, train_and_evaluate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    args = parser.parse_args()
    cfg, graph, topo = load_context(args)
    tcfg = cfg["training"]

    banner("Phase 3: training data")
    start = time.perf_counter()
    table = build_training_table(graph, cfg)
    train_mask, test_mask = split_groups(table, tcfg["test_size"], tcfg["seed"])
    print(f"base topology: {rel(topo)}  seed={tcfg['seed']}  labels={tcfg['labels']}")
    if tcfg["labels"] == "future_outcome":
        print(f"traffic trace: sample {tcfg['trace_steps']} steps (every {tcfg['decision_stride']}), "
              f"{tcfg['synthetic_graphs']} synthetic graphs x {tcfg['synthetic_trace_steps']} steps; "
              f"history={tcfg['history_steps']} horizon={tcfg['horizon_steps']} "
              f"held-out time={tcfg['test_time_fraction']:.0%}")
    else:
        print(f"sample snapshots={tcfg['sample_snapshots']}  synthetic graphs={tcfg['synthetic_graphs']}")
    print(f"k={cfg['k_candidate_paths']}  max_hops={cfg['max_hops']}")
    print(f"rows={len(table)}  queries={table['query'].nunique()}  groups={table['group'].nunique()}")
    held = sorted(table.loc[test_mask & (table['family'] == 'sample').to_numpy(), 'group'].unique())
    print(f"held-out sample pairs (never in training, any snapshot): {', '.join(g.split(':')[1] for g in held)}")

    banner("Phase 3: Random Forest + black-box MLP")
    model, report, blackbox = train_and_evaluate(table, train_mask, test_mask, cfg)
    report["config"] = {"training": tcfg, "k_candidate_paths": cfg["k_candidate_paths"],
                        "max_hops": cfg["max_hops"], "base_topology": rel(topo)}
    report["held_out_sample_pairs"] = held
    report["seconds"] = round(time.perf_counter() - start, 1)

    background = table[train_mask].sample(n=min(tcfg["lime_background_rows"], int(train_mask.sum())),
                                          random_state=tcfg["seed"])
    models_dir = project_dir(cfg, "models_dir")
    save_artifacts(models_dir, model, cfg, report, background, blackbox)
    processed = project_dir(cfg, "processed_dir") / "training_table.csv"
    table.assign(split=["test" if t else "train" for t in test_mask]).to_csv(processed, index=False)

    cv, reg, sel = report["group_cv_mae_train"], report["test_regression"], report["test_selection"]
    vs = sel["vs_hop_count"]
    print(f"rows train/test: {report['rows']['train']}/{report['rows']['test']}   "
          f"queries train/test: {report['queries']['train']}/{report['queries']['test']}")
    print(f"group {cv['folds']}-fold CV MAE (train): {cv['mean']:.4f} +/- {cv['std']:.4f}")
    print(f"held-out MAE: {reg['mae']:.4f}   R^2: {reg['r2']:.4f}")
    print(f"held-out picks, scored by the true label ({report['target']}):")
    names = {"hop_count": "hop count (RIP-like)", "min_delay": "min delay (OSPF-like)",
             "snapshot_rule": "snapshot rule", "blackbox": "AI black-box (MLP)",
             "model": "AI explained (RF)", "oracle": "oracle (hindsight)"}
    print(f"  {'method':<24}{'top-1':>8}{'mean regret':>14}{'mean true cost':>16}")
    for key, label in names.items():
        if key in sel["methods"]:
            m = sel["methods"][key]
            print(f"  {label:<24}{m['top1']:>8.3f}{m['mean_regret']:>14.4f}{m['mean_true_cost']:>16.4f}")
    print(f"  random pick expected top-1: {sel['random_pick_expected_top1']:.3f}")
    vs_snap = sel["vs_snapshot_rule"]
    print(f"vs snapshot rule: model better {vs_snap['model_better']}, tie {vs_snap['tie']}, "
          f"snapshot rule better {vs_snap['snapshot_rule_better']}")
    p = vs["sign_test_p_value"]
    print(f"vs hop-count: model better {vs['model_better']}, tie {vs['tie']}, hop-count better "
          f"{vs['hop_count_better']}  (sign test p={'n/a' if p is None else f'{p:.3g}'})")
    print("top impurity importances: " + ", ".join(
        f"{k}={v:.3f}" for k, v in list(report["feature_importance_impurity"].items())[:5]))

    banner("artifacts")
    for name in ("route_cost_rf.joblib", "route_cost_mlp.joblib", "feature_schema.json", "training_report.json",
                 "xai_background.csv"):
        path = models_dir / name
        if not path.is_file():
            continue
        print(f"{rel(path)}  ({path.stat().st_size / 1024:.0f} KiB)")
    print(f"{rel(processed)}")
    print(f"done in {report['seconds']} s")
    return 0


if __name__ == "__main__":
    run(main)
