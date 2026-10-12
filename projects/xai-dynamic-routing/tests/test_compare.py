import unittest

import pandas as pd

from .helpers import FIXTURES, sample_graph, tmp_dir, trained

from src.evaluate.compare import (
    COLUMNS,
    METHODS,
    choose_pairs,
    comparison_figure,
    head_to_head,
    markdown_report,
    run_comparison,
    summarize,
)
from src.features.path_features import extract_features, path_quality_metrics
from src.routing.recommender import RouteRecommender
from src.topology.load import load_graph


class CompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rec, _, _ = trained()
        cls.graph = sample_graph()
        cls.blackbox = RouteRecommender.load(cls.rec.models_dir, cls.cfg, blackbox=True)
        cls.frame = run_comparison(cls.graph, [("R1", "R8"), ("R2", "R5"), ("R2", "R7")], cls.cfg, cls.rec, "s",
                                   cls.blackbox)

    def test_every_method_per_pair_same_snapshot(self):
        self.assertEqual(list(self.frame.columns), COLUMNS)
        for _, group in self.frame.groupby(["src", "dst"]):
            self.assertEqual(list(group["method"]), list(METHODS))
            self.assertTrue((group["status"] == "ok").all())

    def test_metrics_match_p1_aggregation(self):
        for row in self.frame.itertuples(index=False):
            path = row.path.split("-")
            f = extract_features(self.graph, path)
            q = path_quality_metrics(self.graph, path)
            self.assertEqual(row.hops, f["hops"])
            self.assertAlmostEqual(row.sum_delay, f["sum_delay"])
            self.assertAlmostEqual(row.sum_loss, f["sum_loss"])
            self.assertAlmostEqual(row.max_security_risk, f["max_security_risk"])
            self.assertAlmostEqual(row.path_loss, q["path_loss"])

    def test_baseline_routes_and_ai_note(self):
        rows = self.frame.set_index(["src", "dst", "method"])
        self.assertEqual(rows.loc[("R2", "R5", "RIP"), "path"], "R2-R5")
        self.assertEqual(rows.loc[("R2", "R5", "OSPF"), "path"], "R2-R4-R3-R5")
        self.assertTrue(rows.loc[("R2", "R5", "AI"), "note"].startswith("SHAP: "))
        self.assertTrue(rows.loc[("R2", "R5", "OSPF"), "ai_candidate"])  # mixed candidates contain OSPF path

    def test_failures_are_kept(self):
        graph = load_graph(FIXTURES / "disconnected.json")
        frame = run_comparison(graph, [("A", "C"), ("A", "D"), ("A", "Z")], self.cfg, self.rec, "d")
        status = frame.set_index(["src", "dst", "method"])["status"]
        self.assertEqual(len(frame), 9)
        self.assertTrue((status.loc[("A", "C")] == "ok").all())
        self.assertTrue((status.loc[("A", "D")] == "no_path").all())
        self.assertTrue((status.loc[("A", "Z")] == "error").all())
        summary = summarize(frame)
        self.assertEqual(int(summary["pairs"].iloc[0]), 1)

    def test_outputs(self):
        work = tmp_dir()
        summary = summarize(self.frame)
        self.assertEqual(list(summary["method"]), list(METHODS))
        h2h = head_to_head(self.frame)
        self.assertEqual(h2h["RIP"]["pairs"], 3)
        text = markdown_report(self.frame, summary, h2h, {"topology": "s"})
        self.assertIn("| src | dst | method |", text)
        self.assertEqual(text.count("\n| R2 | R7 |"), 4)
        csv = work / "c.csv"
        self.frame.to_csv(csv, index=False)
        self.assertEqual(len(pd.read_csv(csv)), 12)
        png = work / "c.png"
        comparison_figure(self.frame, png, "t")
        self.assertEqual(png.read_bytes()[:4], b"\x89PNG")

    def test_choose_pairs(self):
        self.assertEqual(choose_pairs(self.graph, self.cfg, is_sample=True)[0], ("R1", "R8"))
        self.assertEqual(len(choose_pairs(self.graph, self.cfg, all_pairs=True)), 56)
        random_pairs = choose_pairs(self.graph, self.cfg, random_pairs=5)
        self.assertEqual(random_pairs, choose_pairs(self.graph, self.cfg, random_pairs=5))
        self.assertEqual(len(set(random_pairs)), 5)
        self.assertEqual(choose_pairs(self.graph, self.cfg, explicit=[("R1", "R2")]), [("R1", "R2")])


if __name__ == "__main__":
    unittest.main()
