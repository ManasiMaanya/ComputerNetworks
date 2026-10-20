"""Attribution drift under blackhole / compromised-node attacks.

    python scripts/attack_drift.py
    python scripts/attack_drift.py --attack blackhole:R5 --attack compromised:R7
    python scripts/attack_drift.py --attack blackhole:R5@2 --pairs R1:R8,R2:R7

Writes outputs/reports/attack_drift.json, .md and outputs/figures/attack_drift.png. The default
attacks target R5 and R7 on the sample topology. Use the same scenario JSONs with
`python scripts/simulate.py --scenario configs/scenarios/blackhole_r5.json` for a full timeline.
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
from src.config import output_dir, project_dir  # noqa: E402
from src.evaluate.attack_drift import (  # noqa: E402
    attack_drift_figure,
    attack_drift_markdown,
    attack_report,
)
from src.routing.recommender import RouteRecommender  # noqa: E402
from src.simulate.attacks import parse_attack_spec  # noqa: E402


def parse_pairs(text: str):
    pairs = []
    for item in text.split(","):
        if ":" not in item:
            raise SystemExit(f"error: bad pair '{item}', expected SRC:DST")
        src, dst = item.split(":", 1)
        pairs.append((src.strip(), dst.strip()))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--attack", action="append", default=None,
                        help="KIND:NODE[@STEP], repeatable (default: blackhole:R5, compromised:R7)")
    parser.add_argument("--step", type=int, default=2, help="default attack step when the spec omits one")
    parser.add_argument("--pairs", default=None, help="comma list SRC:DST,... (default: config compare.pairs)")
    parser.add_argument("--top-k", type=int, default=None, help="top-k for signal detection (default: xai.top_k)")
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--out", default=None, help="JSON report path (default: outputs/reports/attack_drift.json)")
    add_common_args(parser)
    args = parser.parse_args()

    cfg, graph, topo = load_context(args)
    top_k = args.top_k if args.top_k is not None else cfg["xai"]["top_k"]
    specs = args.attack or ["blackhole:R5", "compromised:R7"]
    attacks = [parse_attack_spec(spec, step=args.step) for spec in specs]
    pairs = parse_pairs(args.pairs) if args.pairs else [tuple(pair) for pair in cfg["compare"]["pairs"]]
    recommender = RouteRecommender.load(project_dir(cfg, "models_dir"), cfg)

    banner("Attribution drift under attacks")
    print(f"topology: {rel(topo)}  pairs={len(pairs)}  attacks={len(attacks)}  top_k={top_k}")
    for attack in attacks:
        print(f"  {attack.kind} on {attack.node} at step {attack.step}")
    if recommender.stale_scoring:
        print("warning: config 'scoring' changed since training; explanations describe the loaded model")
    report = attack_report(graph, recommender, cfg, attacks, pairs, top_k=top_k)

    reports = output_dir(cfg, "reports")
    json_path = Path(args.out) if args.out else reports / "attack_drift.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = json_path.with_suffix(".md")
    md_path.write_text(attack_drift_markdown(report), encoding="utf-8")
    saved = [json_path, md_path]
    if not args.no_figures:
        figure = output_dir(cfg, "figures") / "attack_drift.png"
        attack_drift_figure(report, figure)
        saved.append(figure)

    summary = report["summary"]
    banner("summary")
    for key in ("reroute_rate", "detection_rate", "mean_attribution_drift",
                "mean_top_k_overlap", "mean_signal_delta"):
        value = summary.get(key)
        print(f"  {key:<28} {'n/a' if value is None else f'{value:.4f}'}")
    def fmt(value, digits=2):
        return "n/a" if value is None else f"{value:.{digits}f}"

    for item in report["attacks"]:
        stats = item["summary"]
        print(f"  {item['kind']:<11} {item['node']:<4} edges={item['changed_edges']:<2} "
              f"reroute={fmt(stats['reroute_rate'])} "
              f"detect={fmt(stats['detection_rate'])} "
              f"drift={fmt(stats['mean_attribution_drift'], 3)}")
    for path in saved:
        print(f"saved: {rel(path)}")
    return 0


if __name__ == "__main__":
    run(main)
