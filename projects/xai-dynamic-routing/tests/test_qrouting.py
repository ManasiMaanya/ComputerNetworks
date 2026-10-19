import copy
import unittest
from itertools import permutations

import networkx as nx

from .helpers import FIXTURES, sample_graph

from src.config import load_config
from src.errors import NoPathError, RoutingError
from src.routing.baselines import ospf_route
from src.routing.qrouting import qroute_route, qrouting_edge_cost, train_qrouting
from src.simulate.traffic import TrafficParams
from src.topology.load import load_graph

FROZEN = TrafficParams(reversion={"congestion": 0.0, "loss": 0.0, "security_risk": 0.0},
                       noise={"congestion": 0.0, "loss": 0.0, "security_risk": 0.0},
                       burst_prob=0.0, burst_size={}, incident_prob=0.0, incident_size=0.0)


def _tiny_congested_graph() -> nx.Graph:
    """A-B-C is 2 hops of raw delay 10 but both links are badly congested; A-D-C is 2 hops of raw
    delay 12 but uncongested. OSPF(delay) should take A-B-C; Q-routing should avoid it."""
    benign = dict(bandwidth=100, loss=0.01, energy=1.0, security_risk=0.1, utilization=0.3, queue=2,
                 reliability=0.99)
    g = nx.Graph()
    g.add_edge("A", "B", delay=5, congestion=0.9, **benign)
    g.add_edge("B", "C", delay=5, congestion=0.9, **benign)
    g.add_edge("A", "D", delay=6, congestion=0.0, **benign)
    g.add_edge("D", "C", delay=6, congestion=0.0, **benign)
    return g


class QRoutingCostTests(unittest.TestCase):
    def test_formula(self):
        self.assertAlmostEqual(qrouting_edge_cost({"delay": 10, "congestion": 0.5}), 15.0)
        self.assertAlmostEqual(qrouting_edge_cost({"delay": 10, "congestion": 0.0}), 10.0)

    def test_missing_or_invalid_inputs_rejected(self):
        with self.assertRaises(RoutingError):
            qrouting_edge_cost({"congestion": 0.5})
        with self.assertRaises(RoutingError):
            qrouting_edge_cost({"delay": 10})
        with self.assertRaises(RoutingError):
            qrouting_edge_cost({"delay": -1, "congestion": 0.5})
        with self.assertRaises(RoutingError):
            qrouting_edge_cost({"delay": 10, "congestion": -0.1})


class QRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.graph = sample_graph()
        cls.model = train_qrouting(cls.graph, cls.cfg)

    def test_trained_route_is_a_valid_simple_path(self):
        result = qroute_route(self.graph, "R1", "R8", self.model)
        self.assertEqual(result.method, "Q-ROUTE")
        self.assertEqual(result.cost_metric, "delay_ms*(1+congestion)")
        self.assertEqual(result.path[0], "R1")
        self.assertEqual(result.path[-1], "R8")
        self.assertEqual(len(set(result.path)), len(result.path))  # no revisited hop
        self.assertAlmostEqual(result.cost, sum(qrouting_edge_cost(self.graph.edges[u, v])
                                                 for u, v in zip(result.path, result.path[1:])))

    def test_same_config_and_seed_gives_the_same_route(self):
        again = train_qrouting(self.graph, self.cfg)
        a = qroute_route(self.graph, "R1", "R8", self.model)
        b = qroute_route(self.graph, "R1", "R8", again)
        self.assertEqual(a.path, b.path)

    def test_matches_dijkstra_under_frozen_traffic(self):
        """With no traffic noise at all, repeated TD sweeps are just damped Bellman-Ford on a
        static cost graph, so with enough steps and a high learning rate the greedy Q-routing
        path should converge onto the true delay*(1+congestion)-shortest path everywhere."""
        cfg = copy.deepcopy(self.cfg)
        cfg["qrouting"]["learning_rate"] = 0.9
        model = train_qrouting(self.graph, cfg, steps=200, traffic_params=FROZEN)
        for s, d in permutations(sorted(self.graph.nodes()), 2):
            got = qroute_route(self.graph, s, d, model)
            want_cost, want_path = nx.single_source_dijkstra(
                self.graph, s, d, weight=lambda u, v, data: qrouting_edge_cost(data))
            self.assertEqual(got.path, tuple(want_path), f"{s}->{d}")
            self.assertAlmostEqual(got.cost, want_cost, places=6)

    def test_reacts_to_congestion_unlike_static_ospf(self):
        graph = _tiny_congested_graph()
        ospf = ospf_route(graph, "A", "C", "delay")
        self.assertEqual(ospf.path, ("A", "B", "C"))  # lower raw delay (10 < 12), ignores congestion

        cfg = copy.deepcopy(self.cfg)
        cfg["qrouting"]["learning_rate"] = 0.9
        model = train_qrouting(graph, cfg, steps=40, traffic_params=FROZEN)
        qr = qroute_route(graph, "A", "C", model)
        self.assertEqual(qr.path, ("A", "D", "C"))  # routes around the congested link instead
        self.assertAlmostEqual(qr.cost, 12.0)

    def test_unreachable_and_invalid_nodes(self):
        disconnected = load_graph(FIXTURES / "disconnected.json")
        dmodel = train_qrouting(disconnected, self.cfg, steps=20)
        with self.assertRaises(NoPathError):
            qroute_route(disconnected, "A", "D", dmodel)
        with self.assertRaises(RoutingError):
            qroute_route(self.graph, "R1", "X", self.model)
        with self.assertRaises(RoutingError):
            qroute_route(self.graph, "R3", "R3", self.model)


if __name__ == "__main__":
    unittest.main()
