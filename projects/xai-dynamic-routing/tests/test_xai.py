import json
import unittest

import numpy as np

from .helpers import has_module, sample_graph, tmp_dir, trained

from src.features.history import MODEL_COLUMNS
from src.xai.explain import explain_recommendation, explanation_snippet, format_explanation, shap_explanation

PNG = b"\x89PNG\r\n\x1a\n"


class ShapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rec, _, _ = trained()
        cls.result = cls.rec.recommend(sample_graph(), "R1", "R8")
        cls.X = cls.result.X

    def test_additivity_and_feature_names(self):
        s = shap_explanation(self.rec.model, self.X, self.result.chosen, self.result.runner_up)
        self.assertLess(s["additivity_error"], 1e-6)
        self.assertEqual({c["feature"] for c in s["contributions"]}, set(MODEL_COLUMNS))
        total = s["base_value"] + sum(c["contribution"] for c in s["contributions"])
        self.assertAlmostEqual(total, float(self.rec.predict(self.X)[self.result.chosen]), places=6)
        mags = [abs(c["contribution"]) for c in s["contributions"]]
        self.assertEqual(mags, sorted(mags, reverse=True))
        for c in s["contributions"]:
            self.assertEqual(c["value"], float(self.X.iloc[self.result.chosen][c["feature"]]))

    def test_contrast_sums_to_prediction_gap(self):
        s = shap_explanation(self.rec.model, self.X, self.result.chosen, self.result.runner_up)
        gap = sum(c["contribution"] for c in s["contrast"]["contributions"])
        self.assertAlmostEqual(gap, s["contrast"]["predicted_cost_gap"], places=6)
        self.assertLessEqual(s["contrast"]["predicted_cost_gap"], 1e-12)  # chosen is never worse

    def test_no_contrast_with_itself(self):
        s = shap_explanation(self.rec.model, self.X, self.result.chosen, self.result.chosen)
        self.assertNotIn("contrast", s)

    def test_explain_writes_json_and_figure(self):
        work = tmp_dir()
        expl = explain_recommendation(self.result, self.rec, self.cfg, "t_R1_R8", work / "e", work / "f",
                                      lime=has_module("lime"))
        data = json.loads((work / "e" / "explain_t_R1_R8.json").read_text(encoding="utf-8"))
        self.assertEqual(data["recommended_path"], list(self.result.path))
        self.assertEqual(data["feature_columns"], list(MODEL_COLUMNS))
        self.assertIn("lower is better", data["explained_output"])
        png = work / "f" / "shap_t_R1_R8.png"
        self.assertEqual(png.read_bytes()[:8], PNG)
        lines = format_explanation(expl, 5)
        self.assertTrue(any("strongest for" in line for line in lines))
        self.assertTrue(any("strongest against" in line for line in lines))
        self.assertIn("(", explanation_snippet(expl))

    def test_explain_without_figures_or_lime(self):
        work = tmp_dir()
        expl = explain_recommendation(self.result, self.rec, self.cfg, "x", work, work, figures=False, lime=False)
        self.assertFalse(expl["lime"]["available"])
        self.assertNotIn("shap_figure", expl["files"])
        self.assertFalse(any(work.glob("*.png")))

    def test_deterministic(self):
        a = shap_explanation(self.rec.model, self.X, 0, 1)
        b = shap_explanation(self.rec.model, self.X, 0, 1)
        np.testing.assert_array_equal(np.array(a["all_candidates"]), np.array(b["all_candidates"]))


@unittest.skipUnless(has_module("lime"), "optional package 'lime' is not installed (pip install lime)")
class LimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rec, _, _ = trained()
        cls.result = cls.rec.recommend(sample_graph(), "R1", "R8")

    def test_lime_same_instance_and_figure(self):
        work = tmp_dir()
        expl = explain_recommendation(self.result, self.rec, self.cfg, "l", work, work)
        lime = expl["lime"]
        self.assertTrue(lime["available"])
        self.assertTrue(lime["weights"])
        self.assertTrue(all(any(f in w["condition"] for f in MODEL_COLUMNS) for w in lime["weights"]))
        self.assertAlmostEqual(lime["model_prediction"], expl["shap"]["prediction"], places=9)
        self.assertEqual((work / "lime_l.png").read_bytes()[:8], PNG)
        again = explain_recommendation(self.result, self.rec, self.cfg, "l2", work, work, figures=False)
        self.assertEqual(again["lime"]["weights"], lime["weights"])


class LimeMissingTests(unittest.TestCase):
    @unittest.skipIf(has_module("lime"), "lime is installed")
    def test_reports_missing_lime_clearly(self):
        cfg, rec, _, _ = trained()
        result = rec.recommend(sample_graph(), "R1", "R8")
        work = tmp_dir()
        expl = explain_recommendation(result, rec, cfg, "m", work, work, figures=False)
        self.assertFalse(expl["lime"]["available"])
        self.assertIn("pip install lime", expl["lime"]["reason"])


if __name__ == "__main__":
    unittest.main()
