"""End-to-end: run the real CLI scripts with a small config written to a temp folder."""

import json
import subprocess
import sys
import unittest

import pandas as pd

from .helpers import FIXTURES, ROOT, small_config, tmp_dir

from src.features.history import MODEL_COLUMNS


class ScriptPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tmp_dir()
        cls.cfg = small_config(cls.work)
        cls.config_path = cls.work / "config.json"
        cls.config_path.write_text(json.dumps(cls.cfg), encoding="utf-8")
        cls.out = cls.work / "outputs"
        cls.train = cls.script("train.py")

    @classmethod
    def script(cls, name, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / name), "--config", str(cls.config_path),
                               *map(str, args)], cwd=cls.work, capture_output=True, text=True, timeout=900)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_1_train_writes_artifacts(self):
        out = self.ok(self.train)
        self.assertIn("held-out picks", out)
        for method in ("snapshot rule", "AI black-box (MLP)", "AI explained (RF)", "oracle (hindsight)"):
            self.assertIn(method, out)
        self.assertTrue((self.work / "models" / "route_cost_mlp.joblib").exists())
        models = self.work / "models"
        schema = json.loads((models / "feature_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["feature_columns"], list(MODEL_COLUMNS))
        report = json.loads((models / "training_report.json").read_text(encoding="utf-8"))
        self.assertIn("vs_hop_count", report["test_selection"])
        self.assertTrue((self.work / "processed" / "training_table.csv").exists())

    def test_2_infer_with_explanation(self):
        out = self.ok(self.script("infer.py", "--src", "R1", "--dst", "R8", "--explain"))
        self.assertIn("RECOMMENDED:", out)
        self.assertIn("top SHAP contributions", out)
        route = json.loads((self.out / "routes" / "route_sample_topology_R1_R8.json").read_text(encoding="utf-8"))
        self.assertEqual(route["recommended_path"][0], "R1")
        self.assertIn(route["recommended_path"], [c["path"].split("-") for c in route["candidates"]])
        expl = json.loads((self.out / "explanations" / "explain_sample_topology_R1_R8.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(expl["recommended_path"], route["recommended_path"])
        self.assertEqual(expl["feature_columns"], list(MODEL_COLUMNS))
        png = self.out / "figures" / "shap_sample_topology_R1_R8.png"
        self.assertEqual(png.read_bytes()[:4], b"\x89PNG")

    def test_3_infer_errors_without_traceback(self):
        result = self.script("infer.py", "--src", "R1", "--dst", "NOPE")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown node", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_4_compare_sample_and_zoo(self):
        self.ok(self.script("compare.py"))
        frame = pd.read_csv(self.out / "reports" / "compare_sample_topology.csv")
        self.assertEqual(len(frame), 4 * len(self.cfg["compare"]["pairs"]))
        self.assertEqual(set(frame["method"]), {"RIP", "OSPF", "AI", "AI-BB"})
        self.assertTrue((self.out / "reports" / "compare_sample_topology.md").exists())
        self.assertTrue((self.out / "figures" / "compare_sample_topology.png").exists())
        out = self.ok(self.script("compare.py", "--topology", FIXTURES / "zoo_mini.gml", "--all-pairs"))
        self.assertIn("metric provenance", out)
        zoo = pd.read_csv(self.out / "reports" / "compare_zoo_mini.csv")
        self.assertIn("no_path", set(zoo["status"]))  # isolated node kept, not dropped

    def test_5_simulation(self):
        out = self.ok(self.script("simulate.py", "--no-lime"))
        self.assertIn("REROUTE", out)
        history = json.loads((self.out / "simulations" / "sample_incident" / "history.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(len(history["history"]), 10)
        self.assertGreaterEqual(history["reroutes"], 1)

    def test_6_baselines_features_mininet(self):
        self.assertIn("[RIP and OSPF differ]", self.ok(self.script("baselines.py", "--all-pairs")))
        self.assertIn("candidates found", self.ok(self.script("features.py", "--src", "R1", "--dst", "R8")))
        self.ok(self.script("export_mininet.py"))
        self.assertTrue((self.out / "mininet" / "sample_topology_mininet.py").exists())


if __name__ == "__main__":
    unittest.main()
