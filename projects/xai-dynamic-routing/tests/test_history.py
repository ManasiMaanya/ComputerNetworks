"""History features (src/features/history.py, fault F-010)."""

import unittest

from .helpers import sample_graph

from src.features.history import HISTORY_COLUMNS, MODEL_COLUMNS, history_features, model_matrix, model_row
from src.features.path_features import FEATURE_COLUMNS, enumerate_candidates, extract_features
from src.simulate.traffic import generate_trace


def snap(congestion, loss, risk):
    row = {c: 1.0 for c in FEATURE_COLUMNS}
    row.update(mean_congestion=congestion, sum_loss=loss, max_security_risk=risk)
    return row


class HistoryTests(unittest.TestCase):
    def test_mean_and_peak(self):
        h = history_features([snap(0.2, 0.01, 0.1), snap(0.6, 0.05, 0.3), snap(0.4, 0.03, 0.2)])
        self.assertEqual(set(h), set(HISTORY_COLUMNS))
        self.assertAlmostEqual(h["hist_mean_congestion"], 0.4)
        self.assertAlmostEqual(h["hist_max_congestion"], 0.6)
        self.assertAlmostEqual(h["hist_mean_loss"], 0.03)
        self.assertAlmostEqual(h["hist_max_loss"], 0.05)
        self.assertAlmostEqual(h["hist_max_security_risk"], 0.3)

    def test_row_uses_latest_snapshot_in_model_order(self):
        row = model_row([snap(0.9, 0.09, 0.9), snap(0.1, 0.01, 0.1)])
        self.assertEqual(tuple(row), MODEL_COLUMNS)
        self.assertEqual(row["mean_congestion"], 0.1)

    def test_no_history_is_steady_state(self):
        graph = sample_graph()
        cands = enumerate_candidates(graph, "R1", "R8", 3, 8)
        X = model_matrix(cands)
        self.assertEqual(list(X.columns), list(MODEL_COLUMNS))
        for i, cand in enumerate(cands):
            self.assertEqual(X.loc[i, "hist_mean_congestion"], cand.features["mean_congestion"])
            self.assertEqual(X.loc[i, "hist_max_security_risk"], cand.features["max_security_risk"])

    def test_history_graphs_are_summarized(self):
        trace = generate_trace(sample_graph(), 4, 5)
        cands = enumerate_candidates(trace[-1], "R1", "R8", 3, 8)
        X = model_matrix(cands, trace[:-1])
        path = cands[0].nodes
        series = [extract_features(g, path)["mean_congestion"] for g in trace]
        self.assertAlmostEqual(X.loc[0, "hist_mean_congestion"], sum(series) / len(series))
        self.assertAlmostEqual(X.loc[0, "hist_max_congestion"], max(series))

    def test_empty_window_is_rejected(self):
        with self.assertRaises(ValueError):
            history_features([])


if __name__ == "__main__":
    unittest.main()
