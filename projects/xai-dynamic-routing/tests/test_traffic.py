"""Traffic model (src/simulate/traffic.py): ranges, mean reversion, determinism, config validation."""

import copy
import unittest

import numpy as np

from .helpers import sample_graph

from src.config import load_config
from src.errors import ConfigError
from src.simulate.traffic import DYNAMIC_METRICS, TrafficModel, TrafficParams, generate_trace
from src.topology.load import EDGE_ATTRS, METRIC_SPEC

QUIET = {"noise": {"congestion": 0.0, "loss": 0.0, "security_risk": 0.0}, "burst_prob": 0.0, "incident_prob": 0.0}


class TrafficModelTests(unittest.TestCase):
    def test_values_stay_in_metric_ranges_under_heavy_bursts(self):
        graph = sample_graph()
        params = TrafficParams(burst_prob=0.5, burst_size={"congestion": 0.8, "loss": 0.2},
                               incident_prob=0.5, incident_size=0.8)
        model, rng = TrafficModel(graph, params), np.random.default_rng(1)
        for _ in range(50):
            model.step(graph, rng)
        for _, _, data in graph.edges(data=True):
            for metric in EDGE_ATTRS:
                self.assertTrue(METRIC_SPEC[metric].contains(data[metric]), (metric, data[metric]))

    def test_mean_reversion_returns_to_baseline_without_noise(self):
        base = sample_graph()
        graph = copy.deepcopy(base)
        for _, _, data in graph.edges(data=True):
            data["congestion"] = 1.0
        model, rng = TrafficModel(base, TrafficParams(**QUIET)), np.random.default_rng(0)
        for _ in range(80):
            model.step(graph, rng)
        for u, v, data in graph.edges(data=True):
            self.assertAlmostEqual(data["congestion"], base.edges[u, v]["congestion"], places=4)

    def test_only_dynamic_metrics_change(self):
        base = sample_graph()
        for snap in generate_trace(base, steps=20, seed=3):
            for u, v, data in snap.edges(data=True):
                for metric in set(EDGE_ATTRS) - set(DYNAMIC_METRICS):
                    self.assertEqual(data[metric], base.edges[u, v][metric])

    def test_trace_is_deterministic_and_leaves_input_alone(self):
        base = sample_graph()
        before = copy.deepcopy(dict(base.edges.items()))
        a, b = generate_trace(base, 15, 7), generate_trace(base, 15, 7)
        self.assertEqual(len(a), 16)
        self.assertEqual([dict(s.edges.items()) for s in a], [dict(s.edges.items()) for s in b])
        self.assertEqual(dict(base.edges.items()), before)
        self.assertNotEqual(dict(a[0].edges.items()), dict(a[-1].edges.items()))

    def test_changes_are_reported_with_causes(self):
        graph = sample_graph()
        changes = TrafficModel(graph, TrafficParams(burst_prob=1.0)).step(graph, np.random.default_rng(0))
        self.assertTrue(changes)
        self.assertIn("burst", {c["cause"] for c in changes})
        self.assertEqual({"edge", "metric", "old", "new", "cause"}, set(changes[0]))


class TrafficConfigTests(unittest.TestCase):
    def test_default_config_block_is_valid(self):
        params = TrafficParams.from_config(load_config()["traffic"])
        self.assertEqual(set(params.reversion), set(DYNAMIC_METRICS))

    def test_bad_blocks_are_rejected(self):
        for block, fragment in [
            ({"burst_probability": 0.1}, "unknown keys"),
            ({"burst_prob": 1.5}, "burst_prob"),
            ({"reversion": {"congestion": 0.2}}, "reversion"),
            ({"noise": {"congestion": -1, "loss": 0, "security_risk": 0}}, "noise.congestion"),
            ({"burst_size": {"delay": 1.0}}, "burst_size"),
        ]:
            with self.assertRaises(ConfigError) as ctx:
                TrafficParams.from_config(block)
            self.assertIn(fragment, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
