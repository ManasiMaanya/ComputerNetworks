"""Real SNDlib traffic matrices -> P6 simulation (src/topology/sndlib.py::load_demand_matrix,
src/simulate/real_traffic.py, and the real_traffic_dir scenario field in src/simulate/graph_sim.py).

Fixtures: tests/fixtures/sndlib_abilene/abilene.txt is Internet2's real Abilene network; the
traffic/ subdirectory holds four of its real 5-minute traffic matrices
(demandMatrix-abilene-zhang-5min-20040301-000{0,5}.txt, ...-0010.txt, ...-0015.txt) in their own
directory, separate from the base network file -- the shape a real downloaded archive has, and
what src/simulate/real_traffic.py::discover_matrix_files expects `real_traffic_dir` to point at.
Downloaded from SNDlib (http://sndlib.put.poznan.pl/); the files' own META section credits Yin
Zhang's Abilene traffic-matrix study as their source.
"""

import copy
import tarfile
import unittest

import networkx as nx

from .helpers import tmp_dir, trained

from src.config import load_config
from src.errors import ConfigError, TopologyError
from src.simulate.graph_sim import GraphSimulator, parse_scenario
from src.simulate.real_traffic import (
    REAL_METRICS,
    apply_real_traffic,
    discover_matrix_files,
    edge_load,
    extract_matrix_files,
    real_trace,
)
from src.simulate.runner import run_simulation
from src.topology.load import EDGE_ATTRS, METRIC_SPEC
from src.topology.sndlib import load_demand_matrix, load_sndlib

from .helpers import FIXTURES

ABILENE_DIR = FIXTURES / "sndlib_abilene"
ABILENE_NET = ABILENE_DIR / "abilene.txt"
ABILENE_TRAFFIC_DIR = ABILENE_DIR / "traffic"


def _two_hop_graph(bandwidth_ab=100.0, bandwidth_bc=100.0) -> nx.Graph:
    """A-B-C, both edges identical except bandwidth, full EDGE_ATTRS, every dynamic metric at 0."""
    g = nx.Graph()
    base = {"delay": 5.0, "congestion": 0.0, "loss": 0.0, "energy": 1.0, "security_risk": 0.1,
            "utilization": 0.0, "queue": 0.0, "reliability": 0.999}
    g.add_edge("A", "B", **{**base, "bandwidth": bandwidth_ab})
    g.add_edge("B", "C", **{**base, "bandwidth": bandwidth_bc})
    return g


class DemandMatrixTests(unittest.TestCase):
    def test_real_abilene_base_network(self):
        cfg = load_config()
        g = load_sndlib(ABILENE_NET, cfg)
        self.assertEqual(g.number_of_nodes(), 12)
        self.assertEqual(g.number_of_edges(), 15)
        self.assertEqual(len(g.graph["demands"]), 132)

    def test_real_timestamp_file(self):
        nodes = {"ATLAM5", "ATLAng", "CHINng", "DNVRng", "HSTNng", "IPLSng", "KSCYng", "LOSAng",
                 "NYCMng", "SNVAng", "STTLng", "WASHng"}
        dm = load_demand_matrix(ABILENE_TRAFFIC_DIR / "demandMatrix-abilene-zhang-5min-20040301-0000.txt", nodes)
        self.assertEqual(dm.timestamp, "20040301-0000")
        self.assertEqual(len(dm.demands), 132)
        self.assertAlmostEqual(dm.demands[("ATLAM5", "ATLAng")], 0.522208)
        # demands are directed: the reverse pair exists too, but with its own (different) value
        self.assertAlmostEqual(dm.demands[("ATLAng", "ATLAM5")], 0.445149)

    def test_near_zero_demand_is_dropped_not_zeroed(self):
        nodes = {"ATLAM5", "ATLAng", "CHINng", "DNVRng", "HSTNng", "IPLSng", "KSCYng", "LOSAng",
                 "NYCMng", "SNVAng", "STTLng", "WASHng"}
        present = load_demand_matrix(ABILENE_TRAFFIC_DIR / "demandMatrix-abilene-zhang-5min-20040301-0000.txt", nodes)
        dropped = load_demand_matrix(ABILENE_TRAFFIC_DIR / "demandMatrix-abilene-zhang-5min-20040301-0010.txt", nodes)
        self.assertIn(("SNVAng", "ATLAM5"), present.demands)
        self.assertNotIn(("SNVAng", "ATLAM5"), dropped.demands)  # rounded to ~0 and dropped at t=0010

    def test_unknown_node_and_self_loop_and_bad_unit_raise(self):
        path = tmp_dir() / "bad.txt"
        path.write_text("NODES (\n  A ( 0 0 )\n)\nLINKS (\n)\nDEMANDS (\n"
                        "  D1 ( A Q ) 1 0.5 UNLIMITED\n)\n", encoding="utf-8")
        with self.assertRaises(TopologyError) as ctx:
            load_demand_matrix(path, {"A"})
        self.assertIn("unknown node", str(ctx.exception))

        path.write_text("NODES (\n  A ( 0 0 )\n)\nLINKS (\n)\nDEMANDS (\n"
                        "  D1 ( A A ) 1 0.5 UNLIMITED\n)\n", encoding="utf-8")
        with self.assertRaises(TopologyError) as ctx:
            load_demand_matrix(path, {"A"})
        self.assertIn("identical source and destination", str(ctx.exception))

        path.write_text("META (\n  unit = KBITPERSEC\n)\nNODES (\n  A ( 0 0 )\n)\nLINKS (\n)\n"
                        "DEMANDS (\n)\n", encoding="utf-8")
        with self.assertRaises(TopologyError) as ctx:
            load_demand_matrix(path, {"A"})
        self.assertIn("MBITPERSEC", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(TopologyError):
            load_demand_matrix(tmp_dir() / "none.txt", {"A"})

    def test_no_meta_section_is_fine(self):
        path = tmp_dir() / "no_meta.txt"
        path.write_text("NODES (\n  A ( 0 0 )\n  B ( 0 0 )\n)\nLINKS (\n)\nDEMANDS (\n"
                        "  D1 ( A B ) 1 2.5 UNLIMITED\n)\n", encoding="utf-8")
        dm = load_demand_matrix(path, {"A", "B"})
        self.assertIsNone(dm.timestamp)
        self.assertEqual(dm.demands, {("A", "B"): 2.5})


class EdgeLoadFormulaTests(unittest.TestCase):
    """Pin down the exact derivation formulas on a hand-built graph (zoo.py's _synthetic formulas,
    minus the noise term on congestion -- see src/simulate/real_traffic.py's module docstring)."""

    def test_formulas_match_zoo_synthetic_minus_noise(self):
        cfg = load_config()
        g = _two_hop_graph(bandwidth_ab=100.0, bandwidth_bc=100.0)
        updated = apply_real_traffic(g, {("A", "C"): 40.0}, cfg)  # routed A-B-C, 40 Mbps on both edges
        for u, v in (("A", "B"), ("B", "C")):
            data = updated.edges[u, v]
            self.assertAlmostEqual(data["utilization"], 0.4)
            congestion = 0.4 ** 1.5
            self.assertAlmostEqual(data["congestion"], congestion)
            self.assertAlmostEqual(data["loss"], 0.0005 + 0.05 * congestion ** 2)
            self.assertEqual(data["queue"], float(round(25 * congestion)))
            # everything else is left exactly as the base topology had it
            for metric in ("delay", "bandwidth", "energy", "security_risk", "reliability"):
                self.assertEqual(data[metric], g.edges[u, v][metric])

    def test_zero_demand_edge_gets_zero_not_a_leftover_value(self):
        cfg = load_config()
        g = _two_hop_graph()
        g.edges["B", "C"]["congestion"] = 0.9  # pretend leftover synthetic value
        g.edges["B", "C"]["utilization"] = 0.9
        updated = apply_real_traffic(g, {}, cfg)  # no demands at all
        for metric in ("utilization", "congestion", "queue"):
            self.assertEqual(updated.edges["B", "C"][metric], 0.0)
        self.assertAlmostEqual(updated.edges["B", "C"]["loss"], 0.0005)  # the formula's floor

    def test_both_directions_of_a_pair_add_onto_the_same_edge(self):
        cfg = load_config()
        g = _two_hop_graph()
        load = edge_load(g, {("A", "C"): 10.0, ("C", "A"): 15.0}, cfg)
        self.assertAlmostEqual(load[("A", "B")], 25.0)
        self.assertAlmostEqual(load[("B", "C")], 25.0)

    def test_base_graph_is_never_mutated(self):
        cfg = load_config()
        g = _two_hop_graph()
        before = copy.deepcopy(dict(g.edges.items()))
        apply_real_traffic(g, {("A", "C"): 40.0}, cfg)
        self.assertEqual(dict(g.edges.items()), before)

    def test_zero_or_negative_demand_routes_nothing(self):
        cfg = load_config()
        g = _two_hop_graph()
        load = edge_load(g, {("A", "C"): 0.0, ("C", "A"): -5.0}, cfg)
        self.assertEqual(load, {})


class RealTraceTests(unittest.TestCase):
    def test_discover_matrix_files_sorts_chronologically(self):
        paths = discover_matrix_files(ABILENE_TRAFFIC_DIR)
        names = [p.name for p in paths]
        self.assertEqual(names, sorted(names))
        self.assertIn("demandMatrix-abilene-zhang-5min-20040301-0000.txt", names)
        self.assertEqual(len([n for n in names if n.startswith("demandMatrix")]), 4)

    def test_discover_matrix_files_missing_or_empty_dir_raises(self):
        with self.assertRaises(TopologyError):
            discover_matrix_files(tmp_dir() / "nope")
        empty = tmp_dir()
        with self.assertRaises(TopologyError):
            discover_matrix_files(empty)

    def test_real_trace_against_real_fixtures(self):
        cfg = load_config()
        base = load_sndlib(ABILENE_NET, cfg)
        paths = discover_matrix_files(ABILENE_TRAFFIC_DIR)
        rt = real_trace(base, paths, cfg)
        self.assertEqual(len(rt.graphs), 4)
        self.assertEqual(rt.timestamps, ["20040301-0000", "20040301-0005", "20040301-0010", "20040301-0015"])
        for g in rt.graphs:
            self.assertEqual(set(g.nodes()), set(base.nodes()))
            self.assertIsNot(g, base)
            for _, _, data in g.edges(data=True):
                for key in EDGE_ATTRS:
                    self.assertTrue(METRIC_SPEC[key].contains(data[key]))
        # base topology's own metrics are untouched by building the trace
        self.assertEqual(dict(base.edges.items()), dict(load_sndlib(ABILENE_NET, cfg).edges.items()))


class ScenarioFieldTests(unittest.TestCase):
    BASE = {"name": "real", "src": "ATLAM5", "dst": "WASHng", "steps": 4, "seed": 1,
            "real_traffic_dir": "tests/fixtures/sndlib_abilene/traffic"}

    def test_shipped_abilene_scenario_loads(self):
        from src.config import resolve_path
        from src.simulate.graph_sim import load_scenario

        sc = load_scenario(resolve_path("configs/scenarios/abilene_real_traffic.json"))
        self.assertEqual(sc.real_traffic_dir, "data/raw/sndlib/traffic-matrices/abilene")
        self.assertEqual(sc.topology, "data/raw/sndlib/networks/abilene.txt")
        self.assertEqual(sc.steps, 48)
        self.assertFalse(sc.traffic)

    def test_mutually_exclusive_with_traffic(self):
        data = {**copy.deepcopy(self.BASE), "traffic": True}
        with self.assertRaises(ConfigError) as ctx:
            parse_scenario(data)
        self.assertIn("mutually exclusive", str(ctx.exception))

    def test_must_be_a_non_empty_string(self):
        for bad in ("", 7, []):
            with self.assertRaises(ConfigError):
                parse_scenario({**copy.deepcopy(self.BASE), "real_traffic_dir": bad})

    def test_defaults_to_none(self):
        data = copy.deepcopy(self.BASE)
        del data["real_traffic_dir"]
        self.assertIsNone(parse_scenario(data).real_traffic_dir)

    def test_simulator_requires_real_graphs_when_scenario_asks_for_them(self):
        scenario = parse_scenario(copy.deepcopy(self.BASE))
        g = load_sndlib(ABILENE_NET, load_config())
        with self.assertRaises(ConfigError) as ctx:
            GraphSimulator(g, scenario)
        self.assertIn("real_graphs", str(ctx.exception))

    def test_simulator_rejects_a_snapshot_count_mismatch(self):
        cfg = load_config()
        g = load_sndlib(ABILENE_NET, cfg)
        paths = discover_matrix_files(ABILENE_TRAFFIC_DIR)[:2]  # only 2, but scenario says steps=4
        real_graphs = real_trace(g, paths, cfg).graphs
        with self.assertRaises(ConfigError) as ctx:
            GraphSimulator(g, parse_scenario(copy.deepcopy(self.BASE)), real_graphs=real_graphs)
        self.assertIn("must match", str(ctx.exception))

    def test_steps_through_real_snapshots_in_order(self):
        cfg = load_config()
        g = load_sndlib(ABILENE_NET, cfg)
        paths = discover_matrix_files(ABILENE_TRAFFIC_DIR)
        rt = real_trace(g, paths, cfg)
        sim = GraphSimulator(g, parse_scenario(copy.deepcopy(self.BASE)), real_graphs=rt.graphs)
        for t in range(4):
            changes = sim.step(t)
            self.assertTrue(all(c["cause"] == "real_traffic" for c in changes))
            for u, v, data in sim.graph.edges(data=True):
                for metric in REAL_METRICS:
                    self.assertAlmostEqual(data[metric], rt.graphs[t].edges[u, v][metric])

    def test_events_still_apply_on_top_of_real_snapshots(self):
        cfg = load_config()
        g = load_sndlib(ABILENE_NET, cfg)
        paths = discover_matrix_files(ABILENE_TRAFFIC_DIR)
        rt = real_trace(g, paths, cfg)
        data = {**copy.deepcopy(self.BASE),
               "events": [{"step": 1, "edge": ["ATLAM5", "ATLAng"], "set": {"security_risk": 0.95}}]}
        sim = GraphSimulator(g, parse_scenario(data), real_graphs=rt.graphs)
        sim.step(0)
        changes = sim.step(1)
        self.assertEqual(sim.graph.edges["ATLAM5", "ATLAng"]["security_risk"], 0.95)
        self.assertTrue(any(c["cause"] == "event" for c in changes))
        # the real-traffic-derived metrics for that step are still applied, not skipped
        self.assertAlmostEqual(sim.graph.edges["ATLAM5", "ATLAng"]["congestion"],
                               rt.graphs[1].edges["ATLAM5", "ATLAng"]["congestion"])

    def test_end_to_end_through_run_simulation(self):
        cfg, rec, _, _ = trained()
        g = load_sndlib(ABILENE_NET, cfg)
        paths = discover_matrix_files(ABILENE_TRAFFIC_DIR)
        rt = real_trace(g, paths, cfg)
        scenario = parse_scenario(copy.deepcopy(self.BASE))
        result = run_simulation(g, scenario, rec, cfg, tmp_dir(), lime=False, figures=False,
                                log=lambda *_: None, real_graphs=rt.graphs)
        self.assertEqual(len(result["history"]), 4)
        for record in result["history"]:
            self.assertTrue(record["path"])


def _make_tgz(members: dict[str, bytes], tmp_path) -> bytes:
    """A gzipped tar's raw bytes, with the given {archive_path: content} members -- a stand-in
    for a real SNDlib *-native.tgz download (scripts/fetch_sndlib_traffic.py)."""
    archive = tmp_path / "archive.tgz"
    with tarfile.open(archive, mode="w:gz") as tar:
        for name, data in members.items():
            path = tmp_path / "src" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            tar.add(path, arcname=name)
    return archive.read_bytes()


class ExtractMatrixFilesTests(unittest.TestCase):
    """scripts/fetch_sndlib_traffic.py's archive-extraction logic, exercised on a synthetic tgz
    built from the real fixture files -- no network access needed."""

    def setUp(self):
        self.work = tmp_dir()
        real = (ABILENE_TRAFFIC_DIR / "demandMatrix-abilene-zhang-5min-20040301-0000.txt").read_bytes()
        real2 = (ABILENE_TRAFFIC_DIR / "demandMatrix-abilene-zhang-5min-20040301-0005.txt").read_bytes()
        # nested under an archive-root folder, like a real SNDlib tgz, plus an unrelated file to
        # confirm non-matrix members are ignored
        self.archive_bytes = _make_tgz({
            "directed-abilene-zhang-5min-over-6months-ALL-native/"
            "demandMatrix-abilene-zhang-5min-20040301-0005.txt": real2,
            "directed-abilene-zhang-5min-over-6months-ALL-native/"
            "demandMatrix-abilene-zhang-5min-20040301-0000.txt": real,
            "directed-abilene-zhang-5min-over-6months-ALL-native/README.txt": b"not a matrix file",
        }, self.work)

    def test_flattens_sorts_and_matches_real_content(self):
        dest = self.work / "out"
        written = extract_matrix_files(self.archive_bytes, dest, limit=None)
        self.assertEqual([p.name for p in written],
                         ["demandMatrix-abilene-zhang-5min-20040301-0000.txt",
                          "demandMatrix-abilene-zhang-5min-20040301-0005.txt"])
        self.assertEqual(written[0].parent, dest)  # flattened, not nested under the archive's folder
        nodes = {"ATLAM5", "ATLAng", "CHINng", "DNVRng", "HSTNng", "IPLSng", "KSCYng", "LOSAng",
                 "NYCMng", "SNVAng", "STTLng", "WASHng"}
        dm = load_demand_matrix(written[0], nodes)
        self.assertEqual(dm.timestamp, "20040301-0000")
        self.assertAlmostEqual(dm.demands[("ATLAM5", "ATLAng")], 0.522208)

    def test_readme_member_is_not_extracted(self):
        written = extract_matrix_files(self.archive_bytes, self.work / "out2", limit=None)
        self.assertEqual(len(written), 2)
        self.assertFalse((self.work / "out2" / "README.txt").exists())

    def test_limit_keeps_only_the_chronologically_first_files(self):
        written = extract_matrix_files(self.archive_bytes, self.work / "out3", limit=1)
        self.assertEqual([p.name for p in written], ["demandMatrix-abilene-zhang-5min-20040301-0000.txt"])

    def test_negative_limit_means_keep_all(self):
        written = extract_matrix_files(self.archive_bytes, self.work / "out4", limit=-1)
        self.assertEqual(len(written), 2)


if __name__ == "__main__":
    unittest.main()
