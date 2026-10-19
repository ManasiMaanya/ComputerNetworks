import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from .helpers import sample_graph, tmp_dir, trained

from src.config import load_config, resolve_path
from src.errors import ConfigError
from src.simulate.graph_sim import GraphSimulator, load_scenario, parse_scenario
from src.simulate.runner import apply_hysteresis, net_changes, run_simulation
from src.topology.load import EDGE_ATTRS, METRIC_SPEC

BASE = {"name": "t", "src": "R1", "dst": "R8", "steps": 4, "seed": 1,
        "drift": {"metrics": ["congestion"], "sigma": 0.05},
        "events": [{"step": 2, "edge": ["R4", "R6"], "set": {"security_risk": 0.9}, "add": {"loss": 1.5}}]}


class ScenarioTests(unittest.TestCase):
    def test_parse_errors(self):
        for mutate, fragment in [
            (lambda d: d.pop("src"), "'src'"),
            (lambda d: d.update(steps=0), "steps"),
            (lambda d: d["drift"].update(metrics=["jitter"]), "jitter"),
            (lambda d: d["events"][0].update(step=9), "step"),
            (lambda d: d["events"][0].update(set={"latency": 1}), "latency"),
            (lambda d: d["events"][0].update(set={}, add={}), "set"),
        ]:
            data = copy.deepcopy(BASE)
            mutate(data)
            with self.assertRaises(ConfigError) as ctx:
                parse_scenario(data)
            self.assertIn(fragment, str(ctx.exception))

    def test_unknown_event_edge(self):
        data = copy.deepcopy(BASE)
        data["events"][0]["edge"] = ["R1", "R8"]
        with self.assertRaises(ConfigError):
            GraphSimulator(sample_graph(), parse_scenario(data))

    def test_updates_valid_deterministic_and_isolated(self):
        graph = sample_graph()
        before = copy.deepcopy(dict(graph.edges.items()))
        runs = []
        for _ in range(2):
            sim = GraphSimulator(graph, parse_scenario(copy.deepcopy(BASE)))
            log = [sim.step(t) for t in range(4)]
            runs.append((log, copy.deepcopy(dict(sim.graph.edges.items()))))
            for _, _, data in sim.graph.edges(data=True):
                for key in EDGE_ATTRS:
                    self.assertTrue(METRIC_SPEC[key].contains(data[key]))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(dict(graph.edges.items()), before)  # input never modified
        log, final = runs[0]
        self.assertEqual(log[0], [])  # no drift at t=0
        self.assertEqual(final[("R4", "R6")]["security_risk"], 0.9)
        self.assertEqual(final[("R4", "R6")]["loss"], 0.99)  # 0.02 + 1.5 is clipped to the loss maximum
        causes = {c["cause"] for c in log[2]}
        self.assertIn("drift", causes)
        self.assertIn("event", causes)
        self.assertTrue(all(c["metric"] in ("congestion", "security_risk", "loss") for step in log for c in step))

    def test_net_changes(self):
        changes = [{"edge": "A-B", "metric": "loss", "old": 0.1, "new": 0.12, "cause": "drift"},
                   {"edge": "A-B", "metric": "loss", "old": 0.12, "new": 0.5, "cause": "spike"},
                   {"edge": "A-B", "metric": "queue", "old": 1, "new": 2, "cause": "drift"}]
        merged = net_changes(changes)
        self.assertEqual(len(merged), 2)
        self.assertEqual((merged[0]["old"], merged[0]["new"], merged[0]["cause"]), (0.1, 0.5, "drift + spike"))

    def test_shipped_scenario_loads(self):
        cfg = load_config()
        scenario = load_scenario(resolve_path(cfg["simulation"]["scenario"]))
        self.assertEqual(scenario.steps, 10)
        self.assertTrue(scenario.events)


class RunnerTests(unittest.TestCase):
    def test_ten_step_scenario_reroutes_and_explains(self):
        cfg, rec, _, _ = trained()
        scenario = load_scenario(resolve_path(load_config()["simulation"]["scenario"]))
        graph = sample_graph()
        before = copy.deepcopy(dict(graph.edges.items()))
        out = tmp_dir()
        result = run_simulation(graph, scenario, rec, cfg, out, lime=False, figures=True, log=lambda *_: None)
        self.assertEqual(dict(graph.edges.items()), before)
        history = result["history"]
        self.assertEqual(len(history), 10)
        self.assertGreaterEqual(result["reroutes"], 1)
        for prev, cur in zip(history, history[1:]):
            self.assertEqual(cur["rerouted"], cur["path"] != prev["path"])
            self.assertIn(cur["path"], cur["candidates"])
        for record in history:
            if record["rerouted"]:
                self.assertTrue((out / f"explain_{scenario.name}_step{record['step']:02d}.json").exists())
                self.assertTrue((out / f"shap_{scenario.name}_step{record['step']:02d}.png").exists())
                self.assertIn("metric_changes_on_paths", record["reason"])
                expl = json.loads(Path(record["explanation_file"]).read_text(encoding="utf-8"))
                self.assertEqual(expl["recommended_path"], record["path"].split("-"))
        self.assertTrue((out / "history.csv").exists())
        self.assertTrue((out / "timeline.png").exists())
        again = run_simulation(graph, scenario, rec, cfg, tmp_dir(), lime=False, figures=False, log=lambda *_: None)
        self.assertEqual([r["path"] for r in again["history"]], [r["path"] for r in history])



class TrafficScenarioTests(unittest.TestCase):
    def test_traffic_flag_runs_the_traffic_model(self):
        data = {**copy.deepcopy(BASE), "traffic": True, "drift": {"metrics": [], "sigma": 0.0}, "events": []}
        scenario = parse_scenario(data)
        self.assertTrue(scenario.traffic)
        sim = GraphSimulator(sample_graph(), scenario)
        self.assertEqual(sim.step(0), [])
        causes = {c["cause"] for t in range(1, 4) for c in sim.step(t)}
        self.assertTrue(causes <= {"traffic", "burst", "incident"} and causes)
        with self.assertRaises(ConfigError):
            parse_scenario({**copy.deepcopy(BASE), "traffic": "yes"})

    def test_shipped_traffic_scenario_runs_with_history(self):
        cfg, rec, _, _ = trained()
        scenario = load_scenario(resolve_path("configs/scenarios/traffic_dynamics.json"))
        result = run_simulation(sample_graph(), scenario, rec, cfg, tmp_dir(), lime=False, figures=False,
                                log=lambda *_: None)
        self.assertEqual(len(result["history"]), scenario.steps)
        again = run_simulation(sample_graph(), scenario, rec, cfg, tmp_dir(), lime=False, figures=False,
                               log=lambda *_: None)
        self.assertEqual([r["path"] for r in again["history"]], [r["path"] for r in result["history"]])


class HysteresisTests(unittest.TestCase):
    """Anti-flapping (follow-up to F-021): src/simulate/runner.py::apply_hysteresis."""

    @staticmethod
    def _rec(paths_costs: list[tuple[tuple, float]], chosen: int):
        candidates = [SimpleNamespace(nodes=p) for p, _ in paths_costs]
        frame = pd.DataFrame({"predicted_cost": [c for _, c in paths_costs]})
        return SimpleNamespace(candidates=candidates, frame=frame, chosen=chosen)

    def test_holds_a_near_tied_switch(self):
        # new pick is only ~2% cheaper than the previous path: below a 5% margin, hold.
        rec = self._rec([(("A", "B"), 0.50), (("A", "C"), 0.49)], chosen=1)
        self.assertEqual(apply_hysteresis(rec, ("A", "B"), margin=0.05), 0)

    def test_switches_on_a_clear_improvement(self):
        # new pick is 20% cheaper: above a 5% margin, switch.
        rec = self._rec([(("A", "B"), 0.50), (("A", "C"), 0.40)], chosen=1)
        self.assertEqual(apply_hysteresis(rec, ("A", "B"), margin=0.05), 1)

    def test_switches_when_previous_path_is_no_longer_a_candidate(self):
        rec = self._rec([(("A", "C"), 0.49)], chosen=0)
        self.assertEqual(apply_hysteresis(rec, ("A", "B"), margin=0.05), 0)

    def test_zero_margin_never_holds(self):
        rec = self._rec([(("A", "B"), 0.50), (("A", "C"), 0.499)], chosen=1)
        self.assertEqual(apply_hysteresis(rec, ("A", "B"), margin=0.0), 1)

    def test_no_previous_path_keeps_the_models_pick(self):
        rec = self._rec([(("A", "B"), 0.50), (("A", "C"), 0.40)], chosen=1)
        self.assertEqual(apply_hysteresis(rec, None, margin=0.05), 1)

    def test_agreeing_pick_is_a_no_op(self):
        rec = self._rec([(("A", "B"), 0.50), (("A", "C"), 0.40)], chosen=1)
        self.assertEqual(apply_hysteresis(rec, ("A", "C"), margin=0.05), 1)

    def test_shipped_traffic_scenario_flaps_less_with_hysteresis_on(self):
        """Integration check: the default margin must not increase reroutes on the flapping
        scenario (docs/phase-execution-status.md records 11 reroutes at margin 0)."""
        base_cfg, rec, _, _ = trained()
        scenario = load_scenario(resolve_path("configs/scenarios/traffic_dynamics.json"))
        graph = sample_graph()

        off_cfg = copy.deepcopy(base_cfg)
        off_cfg["simulation"]["hysteresis_margin"] = 0.0
        off = run_simulation(graph, scenario, rec, off_cfg, tmp_dir(), lime=False, figures=False,
                             log=lambda *_: None)

        on_cfg = copy.deepcopy(base_cfg)
        on_cfg["simulation"]["hysteresis_margin"] = 0.03
        on = run_simulation(graph, scenario, rec, on_cfg, tmp_dir(), lime=False, figures=False,
                            log=lambda *_: None)

        self.assertLessEqual(on["reroutes"], off["reroutes"])
        held_steps = [r for r in on["history"] if r["held_by_hysteresis"]]
        self.assertTrue(held_steps)
        for r in held_steps:
            self.assertFalse(r["rerouted"])
            self.assertIsNotNone(r["model_top_pick"])

    def test_sample_incident_still_reroutes_on_the_scripted_risk_event(self):
        """A margin that stops noise-level flapping must not delay a genuine, large degradation."""
        cfg, rec, _, _ = trained()
        cfg = copy.deepcopy(cfg)
        cfg["simulation"]["hysteresis_margin"] = 0.03
        scenario = load_scenario(resolve_path(cfg["simulation"]["scenario"]))
        result = run_simulation(sample_graph(), scenario, rec, cfg, tmp_dir(), lime=False, figures=False,
                                log=lambda *_: None)
        self.assertGreaterEqual(result["reroutes"], 1)
        self.assertFalse(any(r["held_by_hysteresis"] for r in result["history"] if r["rerouted"]))


if __name__ == "__main__":
    unittest.main()
