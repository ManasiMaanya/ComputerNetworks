import unittest

import numpy as np
import pandas as pd

from .helpers import sample_graph, small_config

from src.config import load_config
from src.evaluate.label_sensitivity import (
    rule_pick_change_rate,
    study_label_sensitivity,
    weight_scenarios,
)
from src.features.path_features import FEATURE_COLUMNS
from src.routing.scoring import path_cost


def row(**overrides):
    values = {name: 0.0 for name in FEATURE_COLUMNS}
    values.update({"hops": 3, "sum_delay": 10.0, "sum_loss": 0.01, "mean_congestion": 0.2,
                   "max_security_risk": 0.55, "min_bandwidth": 50.0, "min_reliability": 0.95,
                   "mean_energy": 1.0, "max_utilization": 0.5, "max_queue": 5.0})
    values.update(overrides)
    return values


class WeightScenarioTests(unittest.TestCase):
    def test_named_and_random_scenarios_are_normalized(self):
        base = load_config()["scoring"]
        scenarios = weight_scenarios(base, random_draws=2, seed=3)
        for name in ("baseline", "delay_heavy", "risk_heavy", "loss_congestion_heavy",
                     "hop_heavy", "uniform", "random_1", "random_2"):
            self.assertIn(name, scenarios)
        for scoring in scenarios.values():
            self.assertAlmostEqual(sum(scoring["weights"].values()), 1.0, places=9)
            self.assertEqual(scoring["reference"], base["reference"])
            self.assertEqual(scoring["hard_constraints"], base["hard_constraints"])
        self.assertGreater(scenarios["delay_heavy"]["weights"]["delay"], base["weights"]["delay"])
        self.assertGreater(scenarios["risk_heavy"]["weights"]["security_risk"],
                           base["weights"]["security_risk"])
        uniform = list(scenarios["uniform"]["weights"].values())
        self.assertTrue(np.allclose(uniform, uniform[0]))

    def test_random_draw_count_can_be_zero(self):
        scenarios = weight_scenarios(load_config()["scoring"], random_draws=0)
        self.assertNotIn("random_1", scenarios)


class RuleChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load_config()["scoring"]
        cls.scenarios = weight_scenarios(cls.base, random_draws=0)
        # A: fast but risky. B: slow but safe. The baseline prefers A; risk-heavy prefers B.
        a = row()
        b = row(hops=5, sum_delay=40.0, max_security_risk=0.05)
        cls.table = pd.DataFrame([
            {"query": "q", "path_id": 0, **a},
            {"query": "q", "path_id": 1, **b},
        ])
        cls.mask = np.array([True, True])

    def test_weight_change_changes_the_rule_pick(self):
        base_cost = path_cost(self.table[list(FEATURE_COLUMNS)], self.base).to_numpy()
        risk_cost = path_cost(self.table[list(FEATURE_COLUMNS)],
                              self.scenarios["risk_heavy"]).to_numpy()
        self.assertEqual(int(np.argmin(base_cost)), 0)
        self.assertEqual(int(np.argmin(risk_cost)), 1)
        change = rule_pick_change_rate(self.table, self.mask, self.base,
                                       self.scenarios["risk_heavy"])
        self.assertEqual(change["queries"], 1)
        self.assertEqual(change["changed"], 1)
        self.assertEqual(change["change_rate"], 1.0)

    def test_delay_heavy_keeps_the_fast_path(self):
        change = rule_pick_change_rate(self.table, self.mask, self.base,
                                       self.scenarios["delay_heavy"])
        self.assertEqual(change["changed"], 0)


class StudyTests(unittest.TestCase):
    def test_retraining_tracks_the_rule_and_transfer_is_reported(self):
        cfg = small_config()
        cfg["training"].update({"trace_steps": 40, "decision_stride": 4, "synthetic_graphs": 4,
                                "synthetic_trace_steps": 12, "synthetic_decision_stride": 4,
                                "n_estimators": 10, "min_samples_leaf": 2})
        all_scenarios = weight_scenarios(cfg["scoring"], random_draws=0, seed=3)
        selected = {name: all_scenarios[name] for name in ("baseline", "delay_heavy", "risk_heavy")}
        report = study_label_sensitivity(sample_graph(), cfg, scenarios=selected, cv=False,
                                         log=lambda *_: None)
        self.assertEqual(report["baseline"], "baseline")
        self.assertEqual(set(report["scenarios"]), set(selected))
        self.assertEqual(report["scenarios"]["baseline"]["model_vs_baseline"]["change_rate"], 0.0)
        self.assertEqual(report["scenarios"]["baseline"]["rule_vs_baseline"]["change_rate"], 0.0)
        for row in report["scenarios"].values():
            self.assertGreaterEqual(row["model_top1"], 0.0)
            self.assertLessEqual(row["model_top1"], 1.0)
            self.assertEqual(len(row["top_features"]), 5)
            self.assertIn("transfer_from_baseline", row)
        summary = report["summary"]
        self.assertEqual(summary["scenarios"], 3)
        self.assertEqual(report["scenarios"]["baseline"]["rule_vs_baseline"]["queries"],
                         summary["held_out_queries"])
        self.assertEqual(report["scenarios"]["baseline"]["model_vs_baseline"]["queries"],
                         summary["held_out_queries"])
        self.assertIsNotNone(summary["mean_rule_change_rate"])
        self.assertIsNotNone(summary["mean_model_change_rate"])
        self.assertIsNotNone(summary["mean_retrained_top1"])
        self.assertIsNotNone(summary["mean_transfer_top1"])
        self.assertIn("interpretation", summary)


if __name__ == "__main__":
    unittest.main()
