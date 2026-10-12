"""Run the whole demo in order, stopping at the first failing step.

    python scripts/demo.py              # trains only if no model exists yet
    python scripts/demo.py --retrain
    python scripts/demo.py --with-zoo   # also fetch Geant2012 (network) and compare on it

Steps: P0 load -> P1 features -> P2 baselines -> P3 train -> P3/P4 infer --explain ->
P5 compare -> P6 simulate (incident + traffic dynamics) -> (P7 Topology Zoo compare) ->
Mininet export -> Packet Tracer export.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def step(title: str, *args: str) -> None:
    print(f"\n##### {title}: python scripts/{' '.join(args)}", flush=True)
    result = subprocess.run([sys.executable, str(SCRIPTS / args[0]), *args[1:]], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"demo stopped: step '{title}' exited with {result.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--retrain", action="store_true")
    parser.add_argument("--with-zoo", action="store_true")
    parser.add_argument("--zoo-name", default="Geant2012")
    args = parser.parse_args()

    step("P0 load", "load_sample.py")
    step("P1 features", "features.py", "--src", "R1", "--dst", "R8")
    step("P2 baselines", "baselines.py", "--src", "R1", "--dst", "R8")
    step("P2 pairs where RIP != OSPF", "baselines.py", "--all-pairs")
    models = ROOT / "models"
    # Retrain when no model exists or it predates the black-box baseline / history features.
    if args.retrain or not all((models / f).exists() for f in ("route_cost_rf.joblib", "route_cost_mlp.joblib")):
        step("P3 train", "train.py")
    step("P3/P4 infer + explain", "infer.py", "--src", "R1", "--dst", "R8", "--explain")
    step("P5 compare", "compare.py")
    step("P6 simulate (scripted incident)", "simulate.py")
    step("P6 simulate (traffic dynamics)", "simulate.py", "--scenario", "configs/scenarios/traffic_dynamics.json")
    if args.with_zoo:
        step("P7 fetch Topology Zoo", "fetch_topology_zoo.py", "--name", args.zoo_name)
        raw = next((p for p in (ROOT / "data" / "raw").glob(f"{args.zoo_name}.*")
                    if p.suffix in (".gml", ".graphml")), None)
        if raw is None:
            raise SystemExit(f"demo stopped: no {args.zoo_name}.gml/.graphml in data/raw")
        step("P7 compare (delay cost)", "compare.py", "--topology", str(raw))
        step("P7 compare (10^8/bandwidth cost)", "compare.py", "--topology", str(raw),
             "--ospf-cost", "inverse_bandwidth")
    step("P7 Mininet export", "export_mininet.py")
    step("P7 Packet Tracer export", "packet_tracer.py", "export")
    print("\ndemo complete; outputs are under outputs/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
