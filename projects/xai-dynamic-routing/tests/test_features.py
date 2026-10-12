import copy
import math
import unittest

import networkx as nx

from .helpers import FIXTURES, sample_graph

from src.config import load_config
from src.errors import NoPathError, RoutingError, TopologyError
from src.features.path_features import (
    FEATURE_COLUMNS,
    FEATURE_UNITS,
    candidate_paths,
    candidates_frame,
    enumerate_candidates,
    extract_features,
    feature_matrix,
    path_quality_metrics,
)
from src.topology.load import load_graph

EXPECTED_COLUMNS = ("hops", "sum_delay", "max_delay", "min_bandwidth", "max_security_risk", "mean_congestion",
                    "sum_loss", "max_loss", "mean_energy", "max_utilization", "max_queue", "min_reliability")


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = sample_graph()
        cls.cfg = load_config()

    def test_canonical_columns(self):
        self.assertEqual(FEATURE_COLUMNS, EXPECTED_COLUMNS)
        self.assertEqual(set(FEATURE_UNITS), set(FEATURE_COLUMNS))

    def test_r1_r8_acceptance(self):
        k, max_hops = self.cfg["k_candidate_paths"], self.cfg["max_hops"]
        for strategy in ("hops", "delay", "mixed"):
            paths = candidate_paths(self.graph, "R1", "R8", k, max_hops, strategy)
            self.assertTrue(1 <= len(paths) <= k, strategy)
            self.assertEqual(len(set(paths)), len(paths), f"{strategy}: duplicate candidates")
            for path in paths:
                self.assertEqual((path[0], path[-1]), ("R1", "R8"))
                self.assertLessEqual(len(path) - 1, max_hops)
                self.assertEqual(len(set(path)), len(path), "not a simple path")
                self.assertTrue(all(self.graph.has_edge(u, v) for u, v in zip(path, path[1:])))

    def test_hop_order_and_hop_cap(self):
        paths = candidate_paths(self.graph, "R1", "R8", 10, 8, "hops")
        hops = [len(p) - 1 for p in paths]
        self.assertEqual(hops, sorted(hops))
        capped = candidate_paths(self.graph, "R1", "R8", 50, 5, "hops")
        self.assertTrue(all(len(p) - 1 <= 5 for p in capped))
        with self.assertRaises(NoPathError) as ctx:
            candidate_paths(self.graph, "R1", "R8", 5, 3)
        self.assertIn("max_hops=3", str(ctx.exception))

    def test_delay_cap_skips_long_paths(self):
        paths = candidate_paths(self.graph, "R2", "R5", 5, 1, "delay")
        self.assertEqual(paths, [("R2", "R5")])

    def test_mixed_contains_min_hop_and_min_delay_paths(self):
        for src, dst in [("R2", "R7"), ("R2", "R5"), ("R1", "R8")]:
            mixed = candidate_paths(self.graph, src, dst, 5, 8, "mixed")
            self.assertEqual(mixed[0], candidate_paths(self.graph, src, dst, 1, 8, "hops")[0])
            self.assertIn(nx.dijkstra_path(self.graph, src, dst, weight="delay"), [list(p) for p in mixed])

    def test_k_one(self):
        self.assertEqual(len(candidate_paths(self.graph, "R1", "R8", 1, 8)), 1)

    def test_invalid_requests(self):
        with self.assertRaises(RoutingError):
            candidate_paths(self.graph, "R1", "R9", 5, 8)
        with self.assertRaises(RoutingError):
            candidate_paths(self.graph, "R1", "R1", 5, 8)
        with self.assertRaises(RoutingError):
            candidate_paths(self.graph, "R1", "R8", 0, 8)
        with self.assertRaises(RoutingError):
            candidate_paths(self.graph, "R1", "R8", 5, 8, "fastest")

    def test_disconnected_pair(self):
        graph = load_graph(FIXTURES / "disconnected.json")
        with self.assertRaises(NoPathError) as ctx:
            candidate_paths(graph, "A", "D", 5, 8)
        self.assertIn("disconnected", str(ctx.exception))
        self.assertEqual(candidate_paths(graph, "D", "E", 5, 8), [("D", "E")])


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = sample_graph()

    def test_hand_computed_path(self):
        f = extract_features(self.graph, ["R1", "R2", "R4", "R6", "R8"])
        expected = {"hops": 4, "sum_delay": 25, "max_delay": 8, "min_bandwidth": 70, "max_security_risk": 0.25,
                    "mean_congestion": (0.2 + 0.3 + 0.35 + 0.2) / 4, "sum_loss": 0.06, "max_loss": 0.02,
                    "mean_energy": (1.0 + 1.1 + 1.0 + 1.0) / 4, "max_utilization": 0.45, "max_queue": 4,
                    "min_reliability": 0.95}
        self.assertEqual(list(f), list(FEATURE_COLUMNS))
        for key, value in expected.items():
            self.assertAlmostEqual(f[key], value, places=12, msg=key)

    def test_single_link_path(self):
        f = extract_features(self.graph, ["R2", "R5"])
        self.assertEqual(f["hops"], 1)
        self.assertEqual(f["sum_delay"], f["max_delay"])
        self.assertEqual(f["sum_loss"], f["max_loss"])

    def test_direction_does_not_matter_on_undirected_graph(self):
        a = extract_features(self.graph, ["R1", "R3", "R5"])
        b = extract_features(self.graph, ["R5", "R3", "R1"])
        self.assertEqual(a, b)

    def test_malformed_paths(self):
        with self.assertRaises(RoutingError):
            extract_features(self.graph, ["R1"])
        with self.assertRaises(RoutingError):
            extract_features(self.graph, [])
        with self.assertRaises(RoutingError):
            extract_features(self.graph, ["R1", "R2", "R1"])
        with self.assertRaises(TopologyError):
            extract_features(self.graph, ["R1", "R8"])

    def test_missing_or_invalid_metric_in_memory(self):
        graph = copy.deepcopy(self.graph)
        del graph.edges["R1", "R2"]["delay"]
        with self.assertRaises(TopologyError) as ctx:
            extract_features(graph, ["R1", "R2"])
        self.assertIn("R1-R2", str(ctx.exception))
        graph = copy.deepcopy(self.graph)
        graph.edges["R1", "R2"]["bandwidth"] = 0.0
        with self.assertRaises(TopologyError):
            extract_features(graph, ["R1", "R2"])
        graph.edges["R1", "R2"]["bandwidth"] = math.nan
        with self.assertRaises(TopologyError):
            extract_features(graph, ["R1", "R2"])

    def test_probabilistic_loss_and_reliability(self):
        q = path_quality_metrics(self.graph, ["R1", "R2", "R4"])
        self.assertAlmostEqual(q["path_loss"], 1 - 0.99 * 0.98)
        self.assertAlmostEqual(q["path_reliability"], 0.99 * 0.96)
        f = extract_features(self.graph, ["R1", "R2", "R4"])
        self.assertLessEqual(q["path_loss"], f["sum_loss"])  # sum is an upper bound

    def test_frames_keep_path_to_vector_mapping(self):
        cands = enumerate_candidates(self.graph, "R1", "R8", 5, 8)
        frame = candidates_frame(cands, "R1", "R8")
        X = feature_matrix(cands)
        self.assertEqual(list(X.columns), list(FEATURE_COLUMNS))
        for i, cand in enumerate(cands):
            self.assertEqual(frame.loc[i, "path"], cand.label)
            self.assertEqual(list(X.iloc[i]), list(cand.vector()))
            self.assertEqual(extract_features(self.graph, cand.nodes), cand.features)


if __name__ == "__main__":
    unittest.main()
