import copy
import unittest

import pandas as pd

from . import helpers  # noqa: F401  (adds the project root to sys.path)

from src.config import load_config
from src.routing.scoring import path_cost, score_terms

ROW = {"hops": 4, "sum_delay": 25, "max_delay": 8, "min_bandwidth": 70, "max_security_risk": 0.25,
       "mean_congestion": 0.2625, "sum_loss": 0.06, "max_loss": 0.02, "mean_energy": 1.025,
       "max_utilization": 0.45, "max_queue": 4, "min_reliability": 0.95}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.scoring = copy.deepcopy(load_config()["scoring"])

    def cost(self, **overrides):
        return float(path_cost(pd.DataFrame([{**ROW, **overrides}]), self.scoring).iloc[0])

    def test_hand_computed_cost(self):
        w = self.scoring["weights"]
        expected = (w["delay"] * 25 / 50 + w["loss"] * 0.06 / 0.10 + w["congestion"] * 0.2625
                    + w["security_risk"] * 0.25 + w["bandwidth"] * (1 - 70 / 100)
                    + w["reliability"] * 0.05 / 0.20 + w["energy"] * 1.025 / 1.5
                    + w["utilization"] * 0.45 + w["queue"] * 4 / 15 + w["hops"] * 4 / 8)
        self.assertAlmostEqual(self.cost(), expected, places=12)
        self.assertAlmostEqual(self.cost(), 0.395, places=3)  # matches the R1->R8 trace

    def test_monotonic_preferences(self):
        base = self.cost()
        self.assertGreater(self.cost(sum_delay=40), base)
        self.assertGreater(self.cost(sum_loss=0.12), base)
        self.assertGreater(self.cost(max_security_risk=0.5), base)
        self.assertGreater(self.cost(min_reliability=0.8), base)
        self.assertLess(self.cost(min_bandwidth=90), base)

    def test_bandwidth_term_is_clipped(self):
        terms = score_terms(pd.DataFrame([{**ROW, "min_bandwidth": 10000}]), self.scoring)
        self.assertEqual(terms["bandwidth"].iloc[0], 0.0)

    def test_risk_limit_penalty(self):
        limit = self.scoring["hard_constraints"]["max_security_risk"]
        below = self.cost(max_security_risk=limit)
        above = self.cost(max_security_risk=limit + 1e-6)
        self.assertAlmostEqual(above - below, self.scoring["hard_constraints"]["penalty"], places=4)

    def test_weights_are_configurable(self):
        self.scoring["weights"] = {k: 0.0 for k in self.scoring["weights"]}
        self.scoring["weights"]["delay"] = 1.0
        self.assertAlmostEqual(self.cost(), 25 / 50)

    def test_deterministic(self):
        frame = pd.DataFrame([ROW] * 3)
        self.assertEqual(path_cost(frame, self.scoring).tolist(), path_cost(frame, self.scoring).tolist())


if __name__ == "__main__":
    unittest.main()
