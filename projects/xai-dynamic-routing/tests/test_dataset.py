import copy
import unittest

import numpy as np
import pandas as pd

from .helpers import sample_graph, small_config

from src.errors import ModelError
from src.features.history import MODEL_COLUMNS
from src.features.path_features import FEATURE_COLUMNS, extract_features
from src.routing.dataset import (
    OUTCOME_COLUMNS,
    TraceTensor,
    build_training_table,
    pair_group,
    path_feature_series,
    perturb_graph,
    split_groups,
    synthetic_graph,
)
from src.routing.scoring import path_cost
from src.simulate.traffic import TrafficParams, generate_trace
from src.topology.load import EDGE_ATTRS, METRIC_SPEC


class RuleSnapshotDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = small_config()
        cls.cfg["training"].update(labels="rule_snapshot", sample_snapshots=4, synthetic_graphs=4)
        cls.table = build_training_table(sample_graph(), cls.cfg)

    def test_columns_and_labels(self):
        for col in ("family", "snapshot", "group", "query", "src", "dst", "path_id", "path", *FEATURE_COLUMNS,
                    "rule_cost", "is_best"):
            self.assertIn(col, self.table.columns)
        expected = path_cost(self.table[list(FEATURE_COLUMNS)], self.cfg["scoring"])
        np.testing.assert_allclose(self.table["rule_cost"], expected)
        self.assertTrue(self.table.groupby("query")["is_best"].any().all())
        self.assertFalse(self.table[list(FEATURE_COLUMNS)].isna().any().any())
        self.assertLessEqual(self.table.groupby("query").size().max(), self.cfg["k_candidate_paths"])

    def test_sample_family_uses_one_orientation_per_pair(self):
        sample = self.table[self.table["family"] == "sample"]
        pairs = set(zip(sample["src"], sample["dst"]))
        self.assertFalse(any((d, s) in pairs for s, d in pairs))
        self.assertEqual(sample["group"].nunique(), 28)  # C(8, 2)

    def test_reverse_pairs_share_a_group(self):
        graph = sample_graph()
        self.assertEqual(pair_group(graph, "R1", "R8"), pair_group(graph, "R8", "R1"))
        directed = graph.to_directed()
        self.assertNotEqual(pair_group(directed, "R1", "R8"), pair_group(directed, "R8", "R1"))

    def test_split_has_no_group_leakage(self):
        train, test = split_groups(self.table, 0.25, 42)
        self.assertTrue(train.any() and test.any())
        self.assertEqual(set(self.table.loc[train, "group"]) & set(self.table.loc[test, "group"]), set())
        for family in ("sample", "synthetic"):
            fam = self.table["family"] == family
            self.assertTrue((fam & test).any(), f"no test rows for {family}")

    def test_split_needs_two_groups(self):
        tiny = self.table[self.table["group"] == self.table["group"].iloc[0]]
        with self.assertRaises(ModelError):
            split_groups(tiny, 0.25, 1)

    def test_deterministic(self):
        again = build_training_table(sample_graph(), self.cfg)
        pd.testing.assert_frame_equal(self.table, again)

    def test_perturbation_is_valid_and_does_not_touch_input(self):
        graph = sample_graph()
        before = copy.deepcopy(dict(graph.edges.items()))
        snap = perturb_graph(graph, np.random.default_rng(0), 0.8)
        self.assertEqual(dict(graph.edges.items()), before)
        for _, _, data in snap.edges(data=True):
            for key in EDGE_ATTRS:
                self.assertTrue(METRIC_SPEC[key].contains(data[key]), (key, data[key]))

    def test_synthetic_graph_is_connected_and_valid(self):
        graph = synthetic_graph(np.random.default_rng(3), 12, 0)
        self.assertEqual(graph.number_of_nodes(), 12)
        import networkx as nx
        self.assertTrue(nx.is_connected(graph))


class FutureOutcomeDatasetTests(unittest.TestCase):
    """Default labels: the realized rule cost over the next horizon_steps of a simulated trace."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = small_config()
        cls.cfg["training"].update(synthetic_graphs=3)
        cls.table = build_training_table(sample_graph(), cls.cfg)

    def test_columns(self):
        for col in ("t", "period", "target", "rule_cost", *MODEL_COLUMNS, *OUTCOME_COLUMNS):
            self.assertIn(col, self.table.columns)
        self.assertFalse(self.table[list(MODEL_COLUMNS) + ["target"]].isna().any().any())
        self.assertTrue((self.table["target"] == self.table["future_cost"]).all())
        self.assertEqual(set(self.table["period"]), {"train", "test"})

    def test_label_is_the_realized_future_cost(self):
        """Recompute one sample row's label from an independently regenerated trace."""
        tcfg = self.cfg["training"]
        row = self.table[self.table["family"] == "sample"].iloc[37]
        nodes = row["path"].split("-")
        trace = generate_trace(sample_graph(), tcfg["trace_steps"], tcfg["seed"],
                               TrafficParams.from_config(self.cfg["traffic"]))
        t, horizon = int(row["t"]), tcfg["horizon_steps"]
        costs = path_cost(pd.DataFrame([extract_features(g, nodes) for g in trace]), self.cfg["scoring"])
        self.assertAlmostEqual(row["target"], costs.iloc[t + 1: t + horizon + 1].mean())
        self.assertAlmostEqual(row["rule_cost"], costs.iloc[t])
        window = [extract_features(g, nodes) for g in trace[t - tcfg["history_steps"] + 1: t + 1]]
        self.assertAlmostEqual(row["hist_max_congestion"], max(w["mean_congestion"] for w in window))

    def test_split_by_group_and_time(self):
        tcfg = self.cfg["training"]
        train, test = split_groups(self.table, tcfg["test_size"], tcfg["seed"])
        self.assertTrue(train.any() and test.any())
        self.assertEqual(set(self.table.loc[train, "group"]) & set(self.table.loc[test, "group"]), set())
        self.assertTrue((self.table.loc[train, "period"] == "train").all())
        self.assertTrue((self.table.loc[test, "period"] == "test").all())
        sample = self.table["family"] == "sample"
        t_split = int(round((tcfg["trace_steps"] + 1) * (1 - tcfg["test_time_fraction"])))
        self.assertTrue((self.table.loc[train & sample, "t"] + tcfg["horizon_steps"] < t_split).all())
        self.assertTrue((self.table.loc[test & sample, "t"] >= t_split).all())

    def test_vectorized_features_match_extract_features(self):
        trace = generate_trace(sample_graph(), 6, 2)
        tensor = TraceTensor(trace)
        for path in (("R1", "R2", "R4", "R6", "R8"), ("R8", "R7", "R5")):
            fast = path_feature_series(tensor, path)
            slow = pd.DataFrame([extract_features(g, path) for g in trace], columns=list(FEATURE_COLUMNS))
            pd.testing.assert_frame_equal(fast, slow)

    def test_deterministic(self):
        pd.testing.assert_frame_equal(self.table, build_training_table(sample_graph(), self.cfg))


if __name__ == "__main__":
    unittest.main()
