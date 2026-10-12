"""P7: Topology Zoo GML/GraphML and SNDlib loaders, provenance, and comparison on imported graphs."""

import copy
import py_compile
import unittest

from .helpers import FIXTURES, tmp_dir, trained

from src.config import load_config
from src.errors import TopologyError
from src.evaluate.compare import choose_pairs, run_comparison
from src.features.path_features import enumerate_candidates
from src.simulate.mininet_export import mininet_script
from src.topology.load import EDGE_ATTRS, load_topology
from src.topology.provenance import provenance_summary
from src.topology.sndlib import load_sndlib
from src.topology.zoo import haversine_km, load_zoo, parse_speed_label


class SpeedLabelTests(unittest.TestCase):
    def test_labels(self):
        cases = {"10 Gbps": 10000, "1 GB/s": 1000, "2.5 Gbps": 2500, "155 Mbps": 155, "OC-192c": 192 * 51.84,
                 "OC-48": 48 * 51.84, "1-2.5 Gb/s": 1000, "100-155 Mbit/s": 100, "< 100 Mb/s": 100,
                 "45 Mbps DS-3": 45, "10GE": 10000, "Lit Fibre": None, "": None, None: None, "Red Link": None}
        for label, expected in cases.items():
            got = parse_speed_label(label)
            if expected is None:
                self.assertIsNone(got, label)
            else:
                self.assertAlmostEqual(got, expected, msg=label)

    def test_haversine(self):
        self.assertAlmostEqual(haversine_km(48.86, 2.35, 51.51, -0.13), 343.5, delta=2)


class ZooGmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.graph = load_topology(FIXTURES / "zoo_mini.gml", cls.cfg)

    def test_structure(self):
        g = self.graph
        self.assertEqual(g.number_of_nodes(), 6)
        self.assertEqual(g.number_of_edges(), 5)  # parallel Paris-London links collapsed
        self.assertEqual(g.graph["components"], 2)  # Island is isolated
        self.assertIn("Paris", g)
        self.assertIn("Paris_5", g)  # duplicate label made unique
        self.assertEqual(g.edges["London", "Paris"]["parallel_links"], 2)

    def test_documented_bandwidth_and_estimated_delay(self):
        e = self.graph.edges["London", "Paris"]
        self.assertEqual(e["bandwidth"], 10000.0)  # keeps the faster of two parallel links
        self.assertEqual(e["metric_source"]["bandwidth"], "documented")
        km = haversine_km(48.86, 2.35, 51.51, -0.13)
        zcfg = self.cfg["topology_zoo"]
        self.assertAlmostEqual(e["delay"], km / zcfg["propagation_km_per_ms"] + zcfg["per_hop_processing_ms"])
        self.assertEqual(e["metric_source"]["delay"], "estimated")
        self.assertEqual(self.graph.edges["Berlin", "London"]["bandwidth"], 2500.0)
        self.assertAlmostEqual(self.graph.edges["Paris", "Paris_5"]["bandwidth"], 48 * 51.84)
        self.assertEqual(self.graph.edges["Nowhere", "Paris_5"]["bandwidth"], 100.0)

    def test_missing_values_use_defaults_and_are_labelled(self):
        e = self.graph.edges["Berlin", "Nowhere"]
        zcfg = self.cfg["topology_zoo"]
        self.assertEqual(e["bandwidth"], zcfg["default_bandwidth_mbps"])
        self.assertEqual(e["metric_source"]["bandwidth"], "default")
        self.assertEqual(e["delay"], zcfg["default_delay_ms"])
        self.assertEqual(e["metric_source"]["delay"], "default")
        for metric in ("congestion", "loss", "security_risk", "reliability"):
            self.assertEqual(e["metric_source"][metric], "synthetic")

    def test_provenance_summary(self):
        prov = provenance_summary(self.graph)
        self.assertEqual(set(prov), set(EDGE_ATTRS))
        self.assertEqual(sum(prov["delay"].values()), 5)
        self.assertEqual(prov["security_risk"], {"synthetic": 5})

    def test_default_policy_and_determinism(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["topology_zoo"]["missing_metric_policy"] = "default"
        g = load_zoo(FIXTURES / "zoo_mini.gml", cfg)
        e = g.edges["London", "Paris"]
        self.assertEqual(e["security_risk"], cfg["topology_zoo"]["defaults"]["security_risk"])
        self.assertEqual(e["metric_source"]["security_risk"], "default")
        again = load_zoo(FIXTURES / "zoo_mini.gml", self.cfg)
        self.assertEqual(dict(again.edges.items()), dict(self.graph.edges.items()))
        cfg["topology_zoo"]["missing_metric_policy"] = "guess"
        with self.assertRaises(TopologyError):
            load_zoo(FIXTURES / "zoo_mini.gml", cfg)

    def test_malformed_and_missing_files(self):
        bad = tmp_dir() / "bad.gml"
        bad.write_text("graph [ node [ id 0 ", encoding="utf-8")
        with self.assertRaises(TopologyError):
            load_zoo(bad, self.cfg)
        with self.assertRaises(TopologyError):
            load_zoo(tmp_dir() / "none.gml", self.cfg)

    def test_features_and_comparison_with_no_path_pair(self):
        cands = enumerate_candidates(self.graph, "Paris", "Berlin", 5, 8)
        self.assertTrue(cands)
        cfg, rec, _, _ = trained()
        frame = run_comparison(self.graph, [("Paris", "Berlin"), ("Paris", "Island")], cfg, rec, "zoo_mini")
        status = frame.set_index(["src", "dst", "method"])["status"]
        self.assertTrue((status.loc[("Paris", "Berlin")] == "ok").all())
        self.assertTrue((status.loc[("Paris", "Island")] == "no_path").all())


class ZooGraphmlTests(unittest.TestCase):
    def test_graphml_source_format(self):
        g = load_topology(FIXTURES / "zoo_mini.graphml", load_config())
        self.assertFalse(g.is_directed())
        self.assertEqual(sorted(g.nodes()), ["Denver", "Seattle", "Sunnyvale"])
        self.assertAlmostEqual(g.edges["Seattle", "Sunnyvale"]["bandwidth"], 192 * 51.84)
        self.assertEqual(g.edges["Denver", "Sunnyvale"]["bandwidth"], 1000.0)
        self.assertEqual(g.edges["Denver", "Seattle"]["metric_source"]["bandwidth"], "default")
        self.assertEqual(g.edges["Denver", "Seattle"]["link_label"], "Purple Link")
        self.assertTrue(all(d["metric_source"]["delay"] == "default" for *_, d in g.edges(data=True)))


class SndlibTests(unittest.TestCase):
    def test_sndlib_native(self):
        cfg = load_config()
        g = load_sndlib(FIXTURES / "sndlib_mini.txt", cfg)
        self.assertEqual(g.number_of_nodes(), 4)
        self.assertEqual(g.number_of_edges(), 4)
        self.assertEqual(g.edges["Atlanta", "Boston"]["bandwidth"], 155.0)  # largest module
        self.assertEqual(g.edges["Boston", "Chicago"]["bandwidth"], 100.0)  # pre-installed capacity
        self.assertEqual(g.edges["Atlanta", "Boston"]["metric_source"]["delay"], "estimated")
        self.assertEqual([d["id"] for d in g.graph["demands"]], ["D2", "D1", "D3"])
        self.assertEqual(choose_pairs(g, cfg)[0], ("Boston", "Denver"))
        self.assertEqual(load_topology(FIXTURES / "sndlib_mini.txt", cfg).number_of_edges(), 4)

    def test_sndlib_errors(self):
        path = tmp_dir() / "x.txt"
        path.write_text("NODES (\n  A ( 0 0 )\n)\n", encoding="utf-8")
        with self.assertRaises(TopologyError) as ctx:
            load_sndlib(path, load_config())
        self.assertIn("LINKS", str(ctx.exception))
        path.write_text("NODES (\n  A ( 0 0 )\n)\nLINKS (\n  L1 ( A Q ) 0 0 0 0 ( 10 1 )\n)\n", encoding="utf-8")
        with self.assertRaises(TopologyError) as ctx:
            load_sndlib(path, load_config())
        self.assertIn("unknown node 'Q'", str(ctx.exception))


class MininetExportTests(unittest.TestCase):
    def test_script_compiles_and_converts_units(self):
        g = load_topology(FIXTURES / "zoo_mini.gml", load_config())
        text, stats = mininet_script(g, "zoo_mini.gml", "zoo_mini_mininet.py")
        self.assertEqual(stats["links"], 5)
        self.assertEqual(stats["bandwidth_capped"], 3)  # 10G, 2.5G, OC-48 > 1000 Mbps
        path = tmp_dir() / "zoo_mini_mininet.py"
        path.write_text(text, encoding="utf-8")
        py_compile.compile(str(path), doraise=True)
        loss_pct = round(g.edges["London", "Paris"]["loss"] * 100, 4)
        self.assertIn(f"{loss_pct}", text)
        self.assertIn("controller=None", text)


if __name__ == "__main__":
    unittest.main()
