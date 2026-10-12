import copy
import unittest
from itertools import permutations

from .helpers import FIXTURES, sample_graph

from src.config import load_config
from src.errors import NoPathError, RoutingError
from src.routing.baselines import ospf_link_cost, ospf_route, ospf_route_from_config, rip_route
from src.topology.load import load_graph


class BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = sample_graph()

    def test_rip_takes_fewest_hops(self):
        result = rip_route(self.graph, "R2", "R5")
        self.assertEqual(result.path, ("R2", "R5"))
        self.assertEqual((result.cost, result.hops, result.method), (1.0, 1, "RIP"))

    def test_ospf_delay_takes_lowest_delay(self):
        result = ospf_route(self.graph, "R2", "R5", "delay")
        self.assertEqual(result.path, ("R2", "R4", "R3", "R5"))
        self.assertEqual(result.cost, 18.0)  # 8 + 6 + 4 < 20 on the direct link

    def test_ospf_inverse_bandwidth(self):
        result = ospf_route(self.graph, "R1", "R2", "inverse_bandwidth", 1e8)
        self.assertAlmostEqual(result.cost, 1.0)  # 1e8 / (100 Mbps * 1e6)
        self.assertAlmostEqual(ospf_link_cost({"bandwidth": 20}, "inverse_bandwidth", 1e8), 5.0)

    def test_from_config(self):
        result = ospf_route_from_config(self.graph, "R1", "R8", load_config())
        self.assertEqual(result.cost_metric, "delay_ms")
        self.assertEqual(result.cost, 25.0)

    def test_rip_and_ospf_differ_somewhere(self):  # M2
        differ = [(s, d) for s, d in permutations(sorted(self.graph.nodes()), 2)
                  if rip_route(self.graph, s, d).path != ospf_route(self.graph, s, d, "delay").path]
        self.assertIn(("R2", "R5"), differ)

    def test_costs_match_paths(self):
        for s, d in permutations(sorted(self.graph.nodes()), 2):
            ospf = ospf_route(self.graph, s, d, "delay")
            self.assertAlmostEqual(ospf.cost, sum(self.graph.edges[u, v]["delay"]
                                                   for u, v in zip(ospf.path, ospf.path[1:])))
            self.assertEqual(rip_route(self.graph, s, d).cost, rip_route(self.graph, s, d).hops)

    def test_invalid_weights_rejected(self):
        graph = copy.deepcopy(self.graph)
        graph.edges["R1", "R2"]["delay"] = -3.0
        with self.assertRaises(RoutingError) as ctx:
            ospf_route(graph, "R1", "R8", "delay")
        self.assertIn("R1-R2", str(ctx.exception))
        graph = copy.deepcopy(self.graph)
        graph.edges["R1", "R2"]["bandwidth"] = 0
        with self.assertRaises(RoutingError):
            ospf_route(graph, "R1", "R8", "inverse_bandwidth")
        graph = copy.deepcopy(self.graph)
        del graph.edges["R1", "R2"]["delay"]
        with self.assertRaises(RoutingError):
            ospf_route(graph, "R1", "R8", "delay")
        with self.assertRaises(RoutingError):
            ospf_route(self.graph, "R1", "R8", "hops")

    def test_unreachable_and_invalid_nodes(self):
        graph = load_graph(FIXTURES / "disconnected.json")
        for fn in (lambda: rip_route(graph, "A", "E"), lambda: ospf_route(graph, "A", "E")):
            with self.assertRaises(NoPathError):
                fn()
        with self.assertRaises(RoutingError):
            rip_route(self.graph, "R1", "X")
        with self.assertRaises(RoutingError):
            ospf_route(self.graph, "R3", "R3")


if __name__ == "__main__":
    unittest.main()
