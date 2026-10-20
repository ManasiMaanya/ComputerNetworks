import unittest

import numpy as np
import pandas as pd

from .helpers import has_module, sample_graph, tmp_dir, trained

from src.evaluate.explanation_quality import (
    model_seed_stability,
    quality_figure,
    quality_markdown,
    quality_report,
)
from src.features.history import MODEL_COLUMNS
from src.xai.explain import shap_explanation
from src.xai.quality import (
    explanation_quality,
    fidelity_metrics,
    occlusion_deltas,
    parse_lime_weights,
    rank_stats,
    top_features,
    unmatched_lime_conditions,
)


class RankStatsTests(unittest.TestCase):
    def test_identical_and_reversed(self):
        a = {name: float(i + 1) for i, name in enumerate(MODEL_COLUMNS)}
        same = rank_stats(a, a, 3)
        self.assertAlmostEqual(same["spearman"], 1.0)
        self.assertEqual(same["top_k_overlap"], 1.0)
        self.assertAlmostEqual(same["cosine_distance"], 0.0)
        self.assertEqual(same["sign_agreement"], 1.0)

        reverse = {name: -value for name, value in a.items()}
        opposite = rank_stats(a, reverse, 3)
        self.assertAlmostEqual(opposite["spearman"], -1.0)
        self.assertEqual(opposite["top_k_overlap"], 1.0)  # magnitudes are unchanged by the sign flip
        self.assertEqual(opposite["sign_agreement"], 0.0)

    def test_constant_vector_has_no_rank_correlation(self):
        a = {name: 1.0 for name in MODEL_COLUMNS}
        stats = rank_stats(a, {name: float(i) for i, name in enumerate(MODEL_COLUMNS)}, 3)
        self.assertIsNone(stats["spearman"])

    def test_top_features_are_deterministic(self):
        values = {name: 0.0 for name in MODEL_COLUMNS}
        values[MODEL_COLUMNS[3]] = -2.0
        values[MODEL_COLUMNS[7]] = 1.0
        self.assertEqual(top_features(values, 2), [MODEL_COLUMNS[3], MODEL_COLUMNS[7]])


class LimeParsingTests(unittest.TestCase):
    def test_conditions_map_to_model_columns(self):
        lime = {"available": True, "weights": [
            {"condition": "22.99 < sum_delay <= 31.19", "weight": -0.05},
            {"condition": "hist_max_security_risk <= 0.42", "weight": 0.02},
            {"condition": "max_loss <= 0.03", "weight": 0.01},
            {"condition": "3.00 < hops <= 4.00", "weight": 0.007},
            {"condition": "mystery <= 1", "weight": 99.0},
        ]}
        weights = parse_lime_weights(lime)
        self.assertAlmostEqual(weights["sum_delay"], -0.05)
        self.assertAlmostEqual(weights["hist_max_security_risk"], 0.02)
        self.assertAlmostEqual(weights["max_loss"], 0.01)
        self.assertAlmostEqual(weights["hops"], 0.007)
        self.assertNotIn("max_security_risk", weights)  # only the hist_* condition was present
        self.assertEqual(unmatched_lime_conditions(lime), ["mystery <= 1"])

    def test_missing_lime_is_empty(self):
        self.assertEqual(parse_lime_weights({"available": False}), {})
        self.assertEqual(unmatched_lime_conditions({"available": False}), [])


class OcclusionSignTests(unittest.TestCase):
    def test_feature_that_raises_the_prediction_has_positive_occlusion(self):
        class LinearModel:
            def predict(self, frame):
                return np.asarray(frame[MODEL_COLUMNS[0]], dtype=float) * 2.0

        X = pd.DataFrame([{name: 0.0 for name in MODEL_COLUMNS}])
        X.loc[0, MODEL_COLUMNS[0]] = 3.0
        reference = {name: 0.0 for name in MODEL_COLUMNS}
        delta = occlusion_deltas(LinearModel(), X, 0, reference)
        self.assertAlmostEqual(delta[MODEL_COLUMNS[0]], 6.0)  # prediction(original) - prediction(replaced)
        self.assertAlmostEqual(delta[MODEL_COLUMNS[1]], 0.0)


class FidelityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rec, _, _ = trained()
        cls.result = cls.rec.recommend(sample_graph(), "R1", "R8")
        cls.reference = cls.rec.background()[list(MODEL_COLUMNS)].median()
        cls.shap = shap_explanation(cls.rec.model, cls.result.X, cls.result.chosen, None)
        cls.vector = {row["feature"]: row["contribution"] for row in cls.shap["contributions"]}

    def test_occlusion_covers_every_feature(self):
        occ = occlusion_deltas(self.rec.model, self.result.X, self.result.chosen, self.reference)
        self.assertEqual(set(occ), set(MODEL_COLUMNS))
        self.assertTrue(all(np.isfinite(value) for value in occ.values()))
        self.assertGreater(max(abs(value) for value in occ.values()), 0.0)

    def test_fidelity_metrics(self):
        metrics = fidelity_metrics(self.rec.model, self.result.X, self.result.chosen,
                                   self.reference, self.vector, top_k=5, random_trials=16)
        self.assertIsNotNone(metrics["spearman"])
        self.assertGreaterEqual(metrics["spearman"], -1.0)
        self.assertLessEqual(metrics["spearman"], 1.0)
        self.assertGreaterEqual(metrics["top_k_overlap"], 0.0)
        self.assertLessEqual(metrics["top_k_overlap"], 1.0)
        self.assertGreaterEqual(metrics["importance_concentration"], 0.0)
        self.assertEqual(len(metrics["attribution_top_features"]), 5)
        self.assertEqual(len(metrics["occlusion"]), len(MODEL_COLUMNS))
        self.assertLessEqual(abs(self.shap["base_value"] + sum(self.vector.values())
                                 - self.shap["prediction"]), 1e-6)


class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rec, _, cls.table = trained()
        cls.result = cls.rec.recommend(sample_graph(), "R1", "R8")

    def test_without_lime(self):
        quality = explanation_quality(self.result, self.rec, self.cfg, repeats=1,
                                      lime_seeds=[1], top_k=5, include_lime=False)
        self.assertFalse(quality["lime"]["available"])
        self.assertEqual(quality["shap"]["latency_ms"]["n"], 1)
        self.assertGreater(quality["shap"]["latency_ms"]["median_ms"], 0.0)
        self.assertIsNotNone(quality["shap"]["fidelity"]["spearman"])

    @unittest.skipUnless(has_module("lime"), "optional package 'lime' is not installed (pip install lime)")
    def test_lime_agreement_and_seed_stability(self):
        quality = explanation_quality(self.result, self.rec, self.cfg, repeats=1,
                                      lime_seeds=[42, 43], top_k=5, include_lime=True)
        lime = quality["lime"]
        self.assertTrue(lime["available"])
        self.assertEqual(len(lime["seeds"]), 2)
        self.assertIsNotNone(lime["agreement_with_shap"]["spearman"])
        self.assertIsNotNone(lime["seed_stability"]["spearman"])
        self.assertIsNotNone(lime["fidelity"]["spearman"])
        self.assertGreater(lime["latency_ms"]["median_ms"], 0.0)
        self.assertEqual(len(lime["runs"]), 2)

    def test_report_figure_and_markdown(self):
        report = quality_report(self.rec, self.cfg, sample_graph(), [("R1", "R8")],
                                repeats=1, lime_seeds=[None], top_k=5, include_lime=False,
                                log=lambda *_: None)
        self.assertEqual(report["summary"]["pairs"], 1)
        self.assertEqual(report["per_pair"][0]["status"], "ok")
        self.assertIsNotNone(report["summary"]["shap_fidelity_spearman"])
        work = tmp_dir()
        figure = work / "quality.png"
        quality_figure(report, figure)
        self.assertEqual(figure.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("# Explanation quality", quality_markdown(report))

    def test_model_seed_stability(self):
        stability = model_seed_stability(sample_graph(), self.table, self.cfg,
                                         [("R1", "R8"), ("R3", "R8")], [0, 1], top_k=3,
                                         reference_recommender=self.rec)
        self.assertEqual(len(stability["comparisons"]), 2)
        self.assertEqual(stability["summary"]["comparisons"], 2)
        self.assertIsNotNone(stability["summary"]["mean_spearman"])
        self.assertGreaterEqual(stability["summary"]["path_agreement_rate"], 0.0)
        self.assertLessEqual(stability["summary"]["path_agreement_rate"], 1.0)
        self.assertIsNotNone(stability["summary"]["reference_agreement_rate"])


if __name__ == "__main__":
    unittest.main()
