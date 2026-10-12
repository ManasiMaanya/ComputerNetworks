import copy
import json
import unittest
from pathlib import Path

from .helpers import sample_graph, tmp_dir, trained

from src.config import load_config, resolve_path
from src.errors import ConfigError
from src.simulate.graph_sim import GraphSimulator, load_scenario, parse_scenario
from src.simulate.runner import net_changes, run_simulation
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


if __name__ == "__main__":
    unittest.main()
