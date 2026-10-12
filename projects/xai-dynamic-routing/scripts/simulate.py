"""Phase 6: time-stepped metric changes, re-recommend every step, explain every reroute.

    python scripts/simulate.py                                   # scenario from config
    python scripts/simulate.py --scenario configs/scenarios/sample_incident.json

Writes outputs/simulations/<scenario>/history.{csv,json}, timeline.png, and per-reroute
explain_*.json / shap_*.png (and lime_*.png when lime is installed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import banner, rel, run
from src.config import load_config, output_dir, project_dir, resolve_input_path, resolve_path
from src.routing.recommender import RouteRecommender
from src.simulate.graph_sim import load_scenario
from src.simulate.runner import run_simulation
from src.topology.load import load_topology


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--scenario", default=None, help="scenario JSON (default: config simulation.scenario)")
    parser.add_argument("--no-lime", action="store_true")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    scen_path = resolve_input_path(args.scenario) if args.scenario else resolve_path(cfg["simulation"]["scenario"])
    scenario = load_scenario(scen_path)
    topo = resolve_input_path(scenario.topology) if scenario.topology else resolve_path(cfg["sample_topology"])
    graph = load_topology(topo, cfg)
    recommender = RouteRecommender.load(project_dir(cfg, "models_dir"), cfg)

    banner(f"Phase 6: dynamic routing scenario '{scenario.name}'")
    print(f"scenario: {rel(scen_path)}  topology: {rel(topo)}  {scenario.src} -> {scenario.dst}  "
          f"steps={scenario.steps} seed={scenario.seed}")
    print(f"drift: {', '.join(scenario.drift_metrics) or 'none'} sigma={scenario.drift_sigma}  "
          f"events: {len(scenario.events)}")
    if scenario.description:
        print(scenario.description)

    out = output_dir(cfg, "simulations", scenario.name)
    result = run_simulation(graph, scenario, recommender, cfg, out, lime=not args.no_lime,
                            figures=not args.no_figures)

    banner("path history")
    for r in result["history"]:
        mark = "  <-- reroute" if r["rerouted"] else ""
        print(f"t={r['step']:02d}  {r['path']:<22} pred={r['predicted_cost']:.4f}{mark}")
    print(f"\nreroutes: {result['reroutes']}")
    print(f"saved: {rel(out / 'history.csv')}, {rel(out / 'history.json')}"
          + ("" if args.no_figures else f", {rel(out / 'timeline.png')}"))
    return 0


if __name__ == "__main__":
    run(main)
