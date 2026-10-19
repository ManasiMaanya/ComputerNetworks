"""Web demo API (web/app.py), every phase route, against the small test model."""

import copy
import json
import unittest

from .helpers import has_module, tmp_dir, trained

HAVE_WEB = has_module("fastapi") and has_module("httpx")


def client_for(cfg: dict):
    from fastapi.testclient import TestClient

    from web.app import create_app

    path = tmp_dir() / "web_config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return TestClient(create_app(str(path)))


@unittest.skipUnless(HAVE_WEB, "fastapi/httpx not installed")
class WebApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = trained()[0]
        cls.client = client_for(cls.cfg)

    def get(self, path, **params):
        response = self.client.get(path, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_p0_health_and_topology(self):
        self.assertEqual(self.get("/health"), {"status": "ok"})
        self.assertEqual(self.client.get("/").status_code, 200)
        topo = self.get("/api/topology")
        self.assertEqual((topo["node_count"], topo["edge_count"], topo["components"]), (8, 11, 1))
        for node in topo["nodes"]:
            self.assertTrue(0 <= node["x"] <= 1000 and 0 <= node["y"] <= 600)
        self.assertIn("security_risk", topo["edges"][0])

    def test_page_assets_are_versioned_and_revalidated(self):
        # A browser must never pair the current HTML with an older cached app.js/style.css.
        page = self.client.get("/")
        self.assertEqual(page.headers.get("cache-control"), "no-cache")
        self.assertRegex(page.text, r'/static/app\.js\?v=\d+"')
        self.assertRegex(page.text, r'/static/style\.css\?v=\d+"')
        self.assertEqual(self.client.get("/static/app.js").headers.get("cache-control"), "no-cache")

    def test_p7_catalog_has_sample_and_rejects_unknown_ids(self):
        ids = [t["id"] for t in self.get("/api/topologies")["topologies"]]
        self.assertIn("sample", ids)
        self.assertEqual(self.client.get("/api/topology", params={"topology": "../../configs/default.json"}).status_code,
                         404)

    def test_p1_paths(self):
        data = self.get("/api/paths", src="R1", dst="R8")
        self.assertEqual(len(data["candidates"]), self.cfg["k_candidate_paths"])
        first = data["candidates"][0]
        self.assertEqual(first["nodes"][0], "R1")
        self.assertIn("path_loss", first)
        self.assertEqual(set(data["columns"]), set(first["features"]))

    def test_p2_baselines_diverge_on_r1_r7(self):
        data = self.get("/api/baselines", src="R1", dst="R7")
        self.assertEqual(data["rip"]["nodes"], ["R1", "R2", "R5", "R7"])
        self.assertEqual(data["ospf_delay"]["nodes"], ["R1", "R3", "R5", "R7"])
        self.assertEqual(data["rip"]["cost_metric"], "hops")

    def test_p3_infer_returns_a_candidate_and_blackbox_pick(self):
        response = self.client.post("/api/infer", json={"src": "R1", "dst": "R8"})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        ranked = [c["nodes"] for c in data["candidates"]]
        self.assertEqual(data["path"], ranked[0])
        self.assertEqual([c["rank"] for c in data["candidates"]], list(range(1, len(ranked) + 1)))
        self.assertIsNotNone(data["blackbox"])
        self.assertIn(data["blackbox"]["path"], ranked)

    def test_p4_explain_is_additive_with_contrast_and_summary(self):
        data = self.get("/api/explain", src="R1", dst="R8")
        shap = data["shap"]
        total = shap["base_value"] + sum(c["contribution"] for c in shap["contributions"])
        self.assertAlmostEqual(total, shap["prediction"], places=6)
        gap = sum(c["contribution"] for c in shap["contrast"]["contributions"])
        self.assertAlmostEqual(gap, shap["contrast"]["predicted_cost_gap"], places=6)
        self.assertIn("recommended", data["summary"])
        self.assertFalse(data["lime"]["available"])
        if has_module("lime"):
            self.assertTrue(self.get("/api/explain", src="R1", dst="R8", lime="true")["lime"]["available"])

    def test_p5_compare_and_evaluation(self):
        data = self.get("/api/compare", pairs="R1:R8,R2:R5")
        self.assertEqual({r["method"] for r in data["rows"]}, {"RIP", "OSPF", "Q-ROUTE", "AI", "AI-BB"})
        self.assertEqual(len(data["rows"]), 10)
        self.assertEqual(data["summary"][0]["pairs"], 2)
        evaluation = self.get("/api/evaluation")
        self.assertEqual(evaluation["methods"]["oracle"]["mean_regret"], 0.0)
        self.assertIn("snapshot_rule", evaluation["methods"])

    def test_p6_scenarios_and_simulation(self):
        ids = [s["id"] for s in self.get("/api/scenarios")["scenarios"]]
        self.assertIn("sample_incident", ids)
        self.assertIn("traffic_dynamics", ids)
        sim = self.get("/api/simulate", scenario="sample_incident")
        self.assertEqual(len(sim["steps"]), 10)
        self.assertEqual(sim["reroutes"], sum(s["rerouted"] for s in sim["steps"]))
        self.assertIn("explanation", sim["steps"][0])
        self.assertIn("R4-R6.security_risk", sim["steps"][5]["watched"])

    def test_errors_are_clean(self):
        self.assertEqual(self.client.get("/api/paths", params={"src": "R1", "dst": "ZZ"}).status_code, 404)
        self.assertEqual(self.client.get("/api/baselines", params={"src": "R1", "dst": "R1"}).status_code, 422)
        self.assertEqual(self.client.get("/api/simulate", params={"scenario": "nope"}).status_code, 404)
        self.assertEqual(self.client.get("/api/compare", params={"pairs": "R1R8"}).status_code, 422)

    def test_missing_model_gives_503_with_hint(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["models_dir"] = str(tmp_dir() / "empty_models")
        client = client_for(cfg)
        response = client.post("/api/infer", json={"src": "R1", "dst": "R8"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("train.py", response.json()["detail"])
        self.assertEqual(client.get("/api/paths", params={"src": "R1", "dst": "R8"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
