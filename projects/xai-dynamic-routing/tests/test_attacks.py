import copy
import unittest

from .helpers import sample_graph, tmp_dir, trained

from src.config import load_config, resolve_path
from src.errors import ConfigError, RoutingError
from src.evaluate.attack_drift import attack_drift_markdown, attack_report
from src.simulate.attacks import (
    apply_attack,
    attack_events,
    incident_edges,
    parse_attack,
    parse_attack_spec,
)
from src.simulate.graph_sim import GraphSimulator, load_scenario, parse_scenario
from src.simulate.runner import run_simulation
from src.xai.quality import drift_metrics

BASE = {"name": "attack_scenario", "src": "R3", "dst": "R8", "steps": 4, "seed": 1,
        "drift": {"metrics": [], "sigma": 0.0},
        "attacks": [{"kind": "blackhole", "node": "R5", "step": 2}],
        "events": []}


class ParseTests(unittest.TestCase):
    def test_specs_and_validation(self):
        attack = parse_attack_spec("compromised:R7@3")
        self.assertEqual((attack.kind, attack.node, attack.step), ("compromised", "R7", 3))
        with self.assertRaises(ConfigError):
            parse_attack("jamming", "R5")
        with self.assertRaises(ConfigError):
            parse_attack_spec("blackhole")
        with self.assertRaises(ConfigError):
            parse_attack_spec("blackhole:R5@x")
        with self.assertRaises(ConfigError):
            parse_attack("blackhole", "R5", loss=1.5)

    def test_scenario_attacks_parse_and_expand(self):
        scenario = parse_scenario(copy.deepcopy(BASE))
        self.assertEqual(len(scenario.attacks), 1)
        self.assertEqual(scenario.attacks[0].kind, "blackhole")
        graph = sample_graph()
        events = attack_events(graph, scenario.attacks[0], load_config()["evaluation"]["attacks"])
        self.assertEqual(len(events), len(incident_edges(graph, "R5")))
        self.assertTrue(all(event.label == "blackhole R5" for event in events))
        self.assertTrue(all(event.set["loss"] == 0.99 for event in events))

    def test_bad_attack_fields(self):
        for mutate, fragment in [
            (lambda data: data.update(attacks={}), "attacks"),
            (lambda data: data["attacks"][0].update(kind="jamming"), "kind"),
            (lambda data: data["attacks"][0].update(step=9), "step"),
            (lambda data: data["attacks"][0].update(node=""), "node"),
            (lambda data: data["attacks"][0].update(loss=2.0), "loss"),
        ]:
            data = copy.deepcopy(BASE)
            mutate(data)
            with self.assertRaises(ConfigError) as ctx:
                parse_scenario(data)
            self.assertIn(fragment, str(ctx.exception))


class ApplyTests(unittest.TestCase):
    def test_blackhole_modifies_only_incident_edges(self):
        graph = sample_graph()
        before = copy.deepcopy(dict(graph.edges.items()))
        cfg = load_config()
        attacked, meta = apply_attack(graph, parse_attack("blackhole", "R5", 2),
                                      cfg["evaluation"]["attacks"])
        self.assertEqual(meta["changed_edges"], graph.degree("R5"))
        self.assertEqual(meta["effects"], {"loss": 0.99, "reliability": 0.10})
        for u, v in incident_edges(graph, "R5"):
            self.assertAlmostEqual(attacked.edges[u, v]["loss"], 0.99)
            self.assertAlmostEqual(attacked.edges[u, v]["reliability"], 0.10)
        self.assertAlmostEqual(attacked.edges["R1", "R2"]["loss"], 0.01)
        self.assertEqual(dict(graph.edges.items()), before)

    def test_compromised_risk_and_unknown_node(self):
        graph = sample_graph()
        cfg = load_config()
        attacked, meta = apply_attack(graph, parse_attack("compromised", "R7", 2),
                                      cfg["evaluation"]["attacks"])
        self.assertEqual(meta["changed_edges"], 2)
        for u, v in incident_edges(graph, "R7"):
            self.assertAlmostEqual(attacked.edges[u, v]["security_risk"], 0.95)
        with self.assertRaises(RoutingError):
            apply_attack(graph, parse_attack("blackhole", "R99", 2))


class ScenarioRunnerTests(unittest.TestCase):
    def test_attack_is_expanded_and_applied_at_its_step(self):
        graph = sample_graph()
        before = copy.deepcopy(dict(graph.edges.items()))
        cfg = load_config()
        scenario = parse_scenario(copy.deepcopy(BASE))
        sim = GraphSimulator(graph, scenario, attack_defaults=cfg["evaluation"]["attacks"])
        expected = len(incident_edges(graph, "R5")) * (scenario.steps - scenario.attacks[0].step)
        self.assertEqual(len(sim.scenario.events), expected)
        self.assertEqual(sim.step(0), [])
        changes = sim.step(2)
        self.assertIn("blackhole R5", {change["cause"] for change in changes})
        self.assertAlmostEqual(sim.graph.edges["R5", "R7"]["loss"], 0.99)
        self.assertEqual(dict(graph.edges.items()), before)

    def test_attack_is_reasserted_under_traffic(self):
        data = copy.deepcopy(BASE)
        data["traffic"] = True
        data["attacks"][0]["step"] = 1
        cfg = load_config()
        sim = GraphSimulator(sample_graph(), parse_scenario(data),
                             attack_defaults=cfg["evaluation"]["attacks"])
        sim.step(1)
        sim.step(2)
        sim.step(3)
        self.assertAlmostEqual(sim.graph.edges["R5", "R7"]["loss"], 0.99)

    def test_shipped_attack_scenarios_load(self):
        for name in ("blackhole_r5.json", "compromised_r7.json"):
            scenario = load_scenario(resolve_path(f"configs/scenarios/{name}"))
            self.assertEqual(scenario.src, "R3")
            self.assertEqual(scenario.dst, "R8")
            self.assertTrue(scenario.attacks)

    def test_shipped_blackhole_scenario_applies_attack(self):
        """Plumbing check with the small fixture model; model quality is covered elsewhere."""
        cfg, rec, _, _ = trained()
        scenario = load_scenario(resolve_path("configs/scenarios/blackhole_r5.json"))
        result = run_simulation(sample_graph(), scenario, rec, cfg, tmp_dir(), lime=False,
                                figures=False, log=lambda *_: None)
        self.assertEqual(len(result["history"]), scenario.steps)
        after = result["history"][2]
        self.assertIn("blackhole R5", after["events"])
        self.assertAlmostEqual(after["R5-R7.loss"], 0.99)
        self.assertEqual(result["history"][1]["events"], [])  # nothing before the attack step


class DriftTests(unittest.TestCase):
    def test_identical_vectors_do_not_drift(self):
        vector = {"sum_delay": -0.2, "max_security_risk": 0.4, "sum_loss": 0.1}
        stats = drift_metrics(vector, vector, top_k=2)
        self.assertEqual(stats["attribution_drift"], 0.0)
        self.assertEqual(stats["top_k_overlap"], 1.0)
        self.assertFalse(stats["top_feature_changed"])

    def test_shifted_vector_drifts(self):
        before = {"sum_delay": -0.2, "max_security_risk": 0.4, "sum_loss": 0.1}
        after = {"sum_delay": 0.1, "max_security_risk": 0.2, "sum_loss": 0.5}
        stats = drift_metrics(before, after, top_k=2)
        self.assertGreater(stats["attribution_drift"], 0.0)
        self.assertTrue(stats["top_feature_changed"])


class AttackReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rec, _, _ = trained()

    def test_attack_on_the_baseline_path_shifts_shap(self):
        report = attack_report(sample_graph(), self.rec, self.cfg,
                               [parse_attack("blackhole", "R5", 2)], [("R3", "R8")],
                               top_k=5, log=lambda *_: None)
        summary = report["summary"]
        self.assertEqual(summary["affected_pairs"], 1)
        self.assertEqual(summary["reroute_rate"], 1.0)
        self.assertEqual(summary["detection_rate"], 1.0)
        row = report["attacks"][0]["pairs"][0]
        self.assertEqual(row["before_path"], ["R3", "R5", "R7", "R8"])
        self.assertNotIn("R5", row["after_path"])
        self.assertGreater(row["same_path_drift"]["attribution_drift"], 0.0)
        self.assertTrue(row["signal"]["detected"])
        self.assertIn("# Attribution drift", attack_drift_markdown(report))

    def test_compromised_node_detection(self):
        report = attack_report(sample_graph(), self.rec, self.cfg,
                               [parse_attack("compromised", "R7", 2)], [("R3", "R8")],
                               top_k=5, log=lambda *_: None)
        row = report["attacks"][0]["pairs"][0]
        self.assertEqual(row["signal"]["feature"], "max_security_risk")
        self.assertTrue(row["signal"]["detected"])
        self.assertGreater(row["same_path_drift"]["attribution_drift"], 0.0)


if __name__ == "__main__":
    unittest.main()
