"""P0 loader regression tests: F-005 (clear errors), F-007 (attributes), F-012 (M0 check)."""

import copy
import json
import math
import unittest

from .helpers import FIXTURES, sample_graph, tmp_dir

from src.errors import TopologyError
from src.topology.load import EDGE_ATTRS, graph_from_dict, load_graph, load_topology

EDGE = {"delay": 5, "bandwidth": 100, "congestion": 0.2, "loss": 0.01, "energy": 1.0,
        "security_risk": 0.1, "utilization": 0.3, "queue": 2, "reliability": 0.99}


def topo(**edge_overrides):
    edge = {"u": "A", "v": "B", **EDGE, **edge_overrides}
    return {"nodes": ["A", "B"], "edges": [edge]}


class SampleGraphTests(unittest.TestCase):
    def test_m0_counts(self):  # F-012
        graph = sample_graph()
        self.assertEqual((graph.number_of_nodes(), graph.number_of_edges()), (8, 11))
        self.assertEqual(graph.graph["components"], 1)

    def test_all_edge_attributes_present_and_float(self):
        for u, v, data in sample_graph().edges(data=True):
            for key in EDGE_ATTRS:
                self.assertIsInstance(data[key], float, f"{u}-{v} {key}")
        self.assertEqual(sample_graph().edges["R1", "R2"]["delay"], 5.0)


class ValidationTests(unittest.TestCase):
    def err(self, data, fragment):
        with self.assertRaises(TopologyError) as ctx:
            graph_from_dict(data, "t.json")
        self.assertIn(fragment, str(ctx.exception))
        return str(ctx.exception)

    def test_missing_file(self):  # F-005
        with self.assertRaises(TopologyError) as ctx:
            load_graph(tmp_dir() / "missing.json")
        self.assertIn("not found", str(ctx.exception))

    def test_invalid_json(self):
        path = tmp_dir() / "bad.json"
        path.write_text('{"nodes": [', encoding="utf-8")
        with self.assertRaises(TopologyError) as ctx:
            load_graph(path)
        self.assertIn("invalid JSON", str(ctx.exception))
        self.assertIn("bad.json", str(ctx.exception))

    def test_missing_top_level_keys(self):
        self.err({"edges": []}, "'nodes'")
        self.err({"nodes": ["A"]}, "'edges'")

    def test_missing_endpoint_key(self):
        data = topo()
        del data["edges"][0]["v"]
        self.err(data, "missing endpoint 'v'")

    def test_missing_attribute_names_edge(self):  # F-007
        data = topo()
        del data["edges"][0]["delay"]
        msg = self.err(data, "missing required attributes ['delay']")
        self.assertIn("A-B", msg)

    def test_out_of_range_metrics(self):
        self.err(topo(loss=1.5), "'loss'")
        self.err(topo(bandwidth=0), "'bandwidth'")
        self.err(topo(delay=-1), "'delay'")
        self.err(topo(reliability=0), "'reliability'")
        self.err(topo(security_risk=1.2), "'security_risk'")

    def test_non_numeric_and_non_finite(self):
        self.err(topo(delay="fast"), "must be a number")
        self.err(topo(delay=True), "must be a number")
        self.err(topo(delay=math.nan), "finite")
        self.err(topo(delay=math.inf), "finite")

    def test_unknown_endpoint_duplicate_and_self_loop(self):
        data = topo()
        data["edges"][0]["v"] = "Z"
        self.err(data, "'Z' is not in 'nodes'")
        data = topo()
        data["edges"].append(copy.deepcopy(data["edges"][0]))
        self.err(data, "duplicate edge")
        data = topo()
        data["edges"].append({**data["edges"][0], "u": "B", "v": "A"})
        self.err(data, "duplicate edge")
        data = topo()
        data["edges"][0]["v"] = "A"
        self.err(data, "self-loop")

    def test_bad_nodes(self):
        self.err({"nodes": [], "edges": []}, "non-empty")
        self.err({"nodes": ["A", "A"], "edges": []}, "duplicate node")
        self.err({"nodes": [{"name": "A"}], "edges": []}, "without 'id'")
        self.err({"nodes": [""], "edges": []}, "invalid id")

    def test_extra_attributes_preserved(self):  # F-007: nothing silently dropped
        data = topo(link_type="fibre", owner="lab")
        data["nodes"] = [{"id": "A", "role": "core", "site": 1}, "B"]
        graph = graph_from_dict(data)
        self.assertEqual(graph.edges["A", "B"]["link_type"], "fibre")
        self.assertEqual(graph.edges["A", "B"]["owner"], "lab")
        self.assertEqual(graph.nodes["A"], {"role": "core", "site": 1})

    def test_directed_graph(self):
        graph = graph_from_dict({**topo(), "directed": True})
        self.assertTrue(graph.is_directed())
        self.assertTrue(graph.has_edge("A", "B"))
        self.assertFalse(graph.has_edge("B", "A"))
        self.err({**topo(), "directed": "yes"}, "'directed'")

    def test_disconnected_graph(self):
        graph = load_graph(FIXTURES / "disconnected.json")
        self.assertEqual(graph.graph["components"], 2)
        with self.assertRaises(TopologyError):
            load_graph(FIXTURES / "disconnected.json", require_connected=True)

    def test_load_topology_dispatch(self):
        self.assertEqual(load_topology(FIXTURES / "disconnected.json").number_of_nodes(), 5)
        path = tmp_dir() / "graph.csv"
        path.write_text("x", encoding="utf-8")
        with self.assertRaises(TopologyError) as ctx:
            load_topology(path)
        self.assertIn("unsupported", str(ctx.exception))

    def test_roundtrip_file(self):
        path = tmp_dir() / "t.json"
        path.write_text(json.dumps(topo()), encoding="utf-8")
        graph = load_graph(path)
        self.assertEqual(graph.graph["name"], "t")
        self.assertEqual(graph.edges["A", "B"]["queue"], 2.0)


if __name__ == "__main__":
    unittest.main()
