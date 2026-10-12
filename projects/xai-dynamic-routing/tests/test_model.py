"""Training, serialization, loading, inference, and schema checks (integration, small model)."""

import json
import shutil
import unittest

import numpy as np
import pandas as pd

from .helpers import FIXTURES, sample_graph, tmp_dir, trained

from src.errors import ModelError, NoPathError
from src.features.history import MODEL_COLUMNS
from src.features.path_features import candidate_paths
from src.routing.dataset import build_training_table, split_groups
from src.routing.recommender import (
    MODEL_FILE,
    SCHEMA_FILE,
    RouteRecommender,
    evaluate_selection,
    selection_order,
    train_and_evaluate,
)
from src.topology.load import load_graph
from src.xai.explain import explain_recommendation


class ModelPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rec, cls.report, cls.table = trained()

    def test_report_is_complete_and_honest(self):
        r = self.report
        self.assertGreater(r["rows"]["train"], 0)
        self.assertGreater(r["rows"]["test"], 0)
        sel = r["test_selection"]
        self.assertEqual(sel["queries"], r["queries"]["test"])
        vs = sel["vs_hop_count"]
        self.assertEqual(vs["model_better"] + vs["tie"] + vs["hop_count_better"], sel["queries"])
        self.assertGreaterEqual(sel["model_top1_accuracy"], 0.0)
        self.assertLessEqual(sel["model_top1_accuracy"], 1.0)

    def test_small_model_beats_hop_count_more_often_than_not(self):
        vs = self.report["test_selection"]["vs_hop_count"]
        self.assertGreater(vs["model_better"], vs["hop_count_better"])

    def test_artifacts_and_schema(self):
        schema = json.loads((self.rec.models_dir / SCHEMA_FILE).read_text(encoding="utf-8"))
        self.assertEqual(schema["feature_columns"], list(MODEL_COLUMNS))
        self.assertEqual(self.rec.model.n_features_in_, len(MODEL_COLUMNS))
        self.assertEqual(list(self.rec.model.feature_names_in_), list(MODEL_COLUMNS))
        self.assertEqual(list(self.rec.background().columns), list(MODEL_COLUMNS))
        self.assertFalse(self.rec.stale_scoring)

    def test_recommend_returns_a_candidate(self):
        graph = sample_graph()
        result = self.rec.recommend(graph, "R1", "R8")
        valid = candidate_paths(graph, "R1", "R8", self.cfg["k_candidate_paths"], self.cfg["max_hops"],
                                self.cfg["candidate_strategy"])
        self.assertIn(result.path, valid)
        self.assertEqual(sorted(result.frame["rank"]), list(range(1, len(valid) + 1)))
        self.assertEqual(result.frame.loc[result.chosen, "rank"], 1)
        self.assertEqual(result.chosen, int(np.argmin(result.frame["predicted_cost"].round(12))))
        d = result.to_dict()
        self.assertEqual(d["recommended_path"], list(result.path))
        self.assertEqual(list(d["features"]), list(MODEL_COLUMNS))

    def test_recommend_errors(self):
        graph = load_graph(FIXTURES / "disconnected.json")
        with self.assertRaises(NoPathError):
            self.rec.recommend(graph, "A", "D")

    def test_reload_is_identical(self):
        again = RouteRecommender.load(self.rec.models_dir, self.cfg)
        X = self.table[list(MODEL_COLUMNS)].head(50)
        np.testing.assert_array_equal(again.predict(X), self.rec.predict(X))

    def test_missing_and_mismatched_artifacts(self):
        empty = tmp_dir()
        with self.assertRaises(ModelError) as ctx:
            RouteRecommender.load(empty, self.cfg)
        self.assertIn("train.py", str(ctx.exception))
        copy_dir = tmp_dir()
        for name in (MODEL_FILE, SCHEMA_FILE):
            shutil.copy(self.rec.models_dir / name, copy_dir / name)
        schema = json.loads((copy_dir / SCHEMA_FILE).read_text(encoding="utf-8"))
        schema["feature_columns"] = schema["feature_columns"][::-1]
        (copy_dir / SCHEMA_FILE).write_text(json.dumps(schema), encoding="utf-8")
        with self.assertRaises(ModelError) as ctx:
            RouteRecommender.load(copy_dir, self.cfg)
        self.assertIn("do not match", str(ctx.exception))
        (copy_dir / MODEL_FILE).write_bytes(b"not a model")
        with self.assertRaises(ModelError):
            RouteRecommender.load(copy_dir, self.cfg)

    def test_stale_scoring_detected(self):
        import copy
        cfg = copy.deepcopy(self.cfg)
        cfg["scoring"]["weights"]["delay"] += 0.1
        self.assertTrue(RouteRecommender.load(self.rec.models_dir, cfg).stale_scoring)

    def test_training_is_reproducible(self):
        table = self.table
        train, test = split_groups(table, self.cfg["training"]["test_size"], self.cfg["training"]["seed"])
        _, report, _ = train_and_evaluate(table, train, test, self.cfg)
        self.assertEqual(report["test_regression"], self.report["test_regression"])

    def test_insufficient_data(self):
        table = self.table.head(10)
        mask = np.ones(len(table), dtype=bool)
        with self.assertRaises(ModelError):
            train_and_evaluate(table, mask, ~mask, self.cfg)


class SelectionTests(unittest.TestCase):
    def test_tie_break_prefers_fewer_hops_then_index(self):
        order = selection_order(np.array([0.5, 0.2, 0.2, 0.2]), np.array([3, 4, 3, 3]))
        self.assertEqual(list(order), [2, 3, 1, 0])

    def test_evaluate_selection_perfect_model(self):
        table = pd.DataFrame({
            "query": ["q1"] * 3 + ["q2"] * 2,
            "path_id": [0, 1, 2, 0, 1],
            "hops": [2, 3, 3, 1, 2],
            "sum_delay": [30, 10, 20, 5, 9],
            "rule_cost": [0.9, 0.3, 0.5, 0.2, 0.4],
        })
        result = evaluate_selection(table, table["rule_cost"].to_numpy())
        self.assertEqual(result["model_top1_accuracy"], 1.0)
        self.assertEqual(result["model_mean_regret"], 0.0)
        self.assertEqual(result["vs_hop_count"]["model_better"], 1)
        self.assertEqual(result["vs_hop_count"]["tie"], 1)
        self.assertAlmostEqual(result["hop_count_mean_regret"], 0.3)


class DatasetBuildSmokeTest(unittest.TestCase):
    def test_build_is_nonempty(self):
        _, _, _, table = trained()
        self.assertGreater(len(table), 100)
        self.assertEqual(set(table["family"]), {"sample", "synthetic"})
        cfg = trained()[0]
        self.assertGreater(len(build_training_table(sample_graph(), {**cfg, "training": {
            **cfg["training"], "sample_snapshots": 1, "synthetic_graphs": 0}})), 0)



class BlackboxAndMethodsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rec, cls.report, cls.table = trained()

    def test_blackbox_is_saved_loadable_and_never_explained(self):
        bb = RouteRecommender.load(self.rec.models_dir, self.cfg, blackbox=True)
        self.assertEqual(bb.kind, "mlp")
        result = bb.recommend(sample_graph(), "R1", "R8")
        self.assertIn(result.path, [c.nodes for c in result.candidates])
        with self.assertRaises(ModelError):
            explain_recommendation(result, bb, self.cfg, "bb", tmp_dir(), tmp_dir(), figures=False, lime=False)

    def test_methods_scored_by_true_label(self):
        sel = self.report["test_selection"]
        self.assertEqual(sel["true_cost"], "target")
        self.assertEqual(set(sel["methods"]),
                         {"model", "hop_count", "min_delay", "snapshot_rule", "blackbox", "oracle"})
        self.assertEqual(sel["methods"]["oracle"]["mean_regret"], 0.0)
        self.assertEqual(sel["methods"]["oracle"]["top1"], 1.0)
        for stats in sel["methods"].values():
            self.assertGreaterEqual(stats["mean_regret"], -1e-12)
        vs = sel["vs_snapshot_rule"]
        self.assertEqual(vs["model_better"] + vs["tie"] + vs["snapshot_rule_better"], sel["queries"])
        self.assertIn("blackbox_test_regression", self.report)

    def test_recommend_uses_history(self):
        from src.simulate.traffic import generate_trace
        trace = generate_trace(sample_graph(), 6, 3)
        without = self.rec.recommend(trace[-1], "R1", "R8")
        with_hist = self.rec.recommend(trace[-1], "R1", "R8", history=trace[:-1])
        self.assertTrue((without.X["hist_max_congestion"] == without.X["mean_congestion"]).all())
        self.assertFalse(with_hist.X.equals(without.X))


if __name__ == "__main__":
    unittest.main()
