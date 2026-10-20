"""Cisco Packet Tracer integration (src/packet_tracer, scripts/packet_tracer.py).

The generated PTBuilder JavaScript is executed under Node against tests/js/pt_mock.js, a mock of
PT's Script Engine IPC API that enforces real PT rules (device models, port existence and reuse,
cable types). The IOS lines that reach each mock device are then fed to the offline route
simulator, so these tests check what the configs would make PT forward on.
"""

import argparse
import importlib.util
import ipaddress
import json
import os
import shutil
import subprocess
import unittest

import networkx as nx

from .helpers import FIXTURES, ROOT, sample_graph, tmp_dir

from src.config import load_config
from src.packet_tracer import PacketTracerError
from src.packet_tracer.ios import PROTOCOLS, merge_routes, path_static_routes, router_config, static_route_lines
from src.packet_tracer.plan import LAN_PORT, MAX_LINK_PORTS, build_plan
from src.packet_tracer.ptbuilder import build_script, routes_script
from src.packet_tracer.routesim import RoutingSimulation
from src.packet_tracer.tracert import check_trace, parse_tracert
from src.routing.baselines import ospf_route_from_config, rip_route
from src.topology.load import load_topology

MOCK = ROOT / "tests" / "js" / "pt_mock.js"
NODE = shutil.which("node")
AI_PATH = ["R1", "R2", "R4", "R6", "R8", "R7"]

TRACE = """C:\\>tracert 192.168.7.10

Tracing route to 192.168.7.10 over a maximum of 30 hops:

  1   0 ms      0 ms      0 ms      192.168.1.1
  2   0 ms      0 ms      0 ms      {r3}
  3   *         *         *         Request timed out.
  4   1 ms      0 ms      0 ms      {r7}
  5   0 ms      0 ms      0 ms      192.168.7.10

Trace complete.
"""


def configs(plan, protocol):
    return {r: router_config(plan, r, protocol) for r in plan.routers}


def trace_for(plan, path, dst_ip):
    hops = [plan.lan(path[0]).ip] + [plan.link_interface(b, a).ip for a, b in zip(path, path[1:])] + [dst_ip]
    lines = [f"C:\\>tracert {dst_ip}", "", f"Tracing route to {dst_ip} over a maximum of 30 hops:", ""]
    lines += [f"  {i}   0 ms      0 ms      0 ms      {ip}" for i, ip in enumerate(hops, start=1)]
    return "\n".join(lines + ["", "Trace complete."])


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = sample_graph()
        cls.plan = build_plan(cls.graph)

    def test_addresses_unique_and_links_share_a_30(self):
        plan = self.plan
        ips = [i.ip for ifaces in plan.interfaces.values() for i in ifaces] + [h.ip for h in plan.hosts.values()]
        self.assertEqual(len(ips), len(set(ips)))
        for c in plan.cables:
            if c.kind != "cross":
                continue
            a = next(i for i in plan.interfaces[c.a_device] if i.port == c.a_port)
            b = next(i for i in plan.interfaces[c.b_device] if i.port == c.b_port)
            self.assertEqual(a.network, b.network)
            self.assertEqual(a.network.prefixlen, 30)
            self.assertEqual(a.ospf_cost, b.ospf_cost)

    def test_ports_cables_and_hosts(self):
        plan = self.plan
        self.assertEqual(len(plan.cables), self.graph.number_of_edges() + self.graph.number_of_nodes())
        used = [(c.a_device, c.a_port) for c in plan.cables] + [(c.b_device, c.b_port) for c in plan.cables]
        self.assertEqual(len(used), len(set(used)))
        for router in plan.routers:
            self.assertEqual(plan.lan(router).port, LAN_PORT)
            host = plan.hosts[router]
            self.assertIn(ipaddress.IPv4Address(host.ip), plan.lan_network(router))
            self.assertEqual(host.gateway, plan.lan(router).ip)

    def test_rejects_directed_and_oversized(self):
        with self.assertRaises(PacketTracerError):
            build_plan(nx.DiGraph([("A", "B")]))
        star = nx.star_graph(MAX_LINK_PORTS + 1)
        nx.set_edge_attributes(star, 1.0, "delay")
        with self.assertRaises(PacketTracerError):
            build_plan(star)

    def test_real_topology_fixture(self):
        graph = load_topology(FIXTURES / "zoo_mini.gml", load_config())
        plan = build_plan(graph)
        sim = RoutingSimulation(plan, configs(plan, "ospf"))
        self.assertEqual(sim.errors, [])
        component = max(nx.connected_components(graph), key=len)
        a, b = sorted(map(str, component))[:2]
        self.assertTrue(sim.paths(a, b))


class RoutingSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.graph = sample_graph()
        cls.plan = build_plan(cls.graph)

    def test_ospf_configs_route_like_the_ospf_baseline(self):
        sim = RoutingSimulation(self.plan, configs(self.plan, "ospf"))
        self.assertEqual(sim.errors, [])
        weighted = nx.Graph()
        for u, v, d in self.graph.edges(data=True):
            weighted.add_edge(u, v, w=max(1, round(d["delay"])))
        for src in self.plan.routers:
            for dst in self.plan.routers:
                if src != dst:
                    expected = {tuple(p) for p in nx.all_shortest_paths(weighted, src, dst, weight="w")}
                    self.assertEqual(sim.paths(src, dst), expected)
                    self.assertIn(ospf_route_from_config(self.graph, src, dst, self.cfg).path, expected)

    def test_rip_configs_route_by_hop_count(self):
        sim = RoutingSimulation(self.plan, configs(self.plan, "rip"))
        self.assertEqual(sim.errors, [])
        for src in self.plan.routers:
            for dst in self.plan.routers:
                if src != dst:
                    expected = {tuple(p) for p in nx.all_shortest_paths(self.graph, src, dst)}
                    self.assertEqual(sim.paths(src, dst), expected)
                    self.assertIn(rip_route(self.graph, src, dst).path, expected)

    def test_ai_static_routes_pin_both_directions(self):
        for protocol in PROTOCOLS:
            cfgs = configs(self.plan, protocol)
            for router, routes in path_static_routes(self.plan, AI_PATH).items():
                cfgs[router] = cfgs[router] + static_route_lines(routes)
            sim = RoutingSimulation(self.plan, cfgs)
            self.assertEqual(sim.paths("R1", "R7"), {tuple(AI_PATH)})
            self.assertEqual(sim.paths("R7", "R1"), {tuple(reversed(AI_PATH))})
            self.assertEqual(sim.route_source("R1", "R7"), "static")

    def test_undo_restores_the_baseline(self):
        cfgs = configs(self.plan, "ospf")
        for router, routes in path_static_routes(self.plan, AI_PATH).items():
            cfgs[router] = cfgs[router] + static_route_lines(routes) + static_route_lines(routes, remove=True)
        baseline = RoutingSimulation(self.plan, configs(self.plan, "ospf")).paths("R1", "R7")
        self.assertEqual(RoutingSimulation(self.plan, cfgs).paths("R1", "R7"), baseline)

    def test_conflicting_paths_are_rejected(self):
        with self.assertRaises(PacketTracerError):
            merge_routes(self.plan, [["R1", "R2", "R5", "R7"], ["R2", "R4", "R6", "R8", "R7"]])

    def test_config_mistakes_are_caught(self):
        cfgs = configs(self.plan, "ospf")
        cfgs["R5"] = [line for line in cfgs["R5"] if line.strip() != "ip routing"]
        with self.assertRaises(PacketTracerError):
            RoutingSimulation(self.plan, cfgs).paths("R3", "R7")
        cfgs = configs(self.plan, "ospf")
        cfgs["R2"] = [line for line in cfgs["R2"] if line.strip() != "no switchport"]
        self.assertTrue(any("no switchport" in e for e in RoutingSimulation(self.plan, cfgs).errors))


class TracertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = build_plan(sample_graph())

    def test_parse_with_timeouts(self):
        target, hops = parse_tracert(TRACE.format(r3="10.0.0.6", r7="10.0.0.34"))
        self.assertEqual(target, "192.168.7.10")
        self.assertEqual(hops, ["192.168.1.1", "10.0.0.6", None, "10.0.0.34", "192.168.7.10"])

    def test_match_mismatch_and_unknown(self):
        plan = self.plan
        expected = RoutingSimulation(plan, configs(plan, "ospf")).paths("R1", "R7")
        good = TRACE.format(r3=plan.link_interface("R3", "R1").ip, r7=plan.link_interface("R7", "R5").ip)
        result = check_trace(plan, good, expected)
        self.assertTrue(result.ok)
        self.assertEqual(result.matched, ("R1", "R3", "R5", "R7"))
        wrong = TRACE.format(r3=plan.link_interface("R2", "R1").ip, r7=plan.link_interface("R7", "R5").ip)
        self.assertFalse(check_trace(plan, wrong, expected).ok)
        unknown = TRACE.format(r3="172.16.0.1", r7=plan.link_interface("R7", "R5").ip)
        self.assertEqual(check_trace(plan, unknown, expected).unknown_ips, ["172.16.0.1"])
        with self.assertRaises(PacketTracerError):
            parse_tracert("nothing useful")


class CliVerifyTests(unittest.TestCase):
    def test_verify_against_a_manifest(self):
        spec = importlib.util.spec_from_file_location("pt_cli", ROOT / "scripts" / "packet_tracer.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        cfg, plan, work = load_config(), build_plan(sample_graph()), tmp_dir()
        (work / "manifest.json").write_text(json.dumps(
            {"topology": "data/samples/sample_topology.json", "pairs": [{"ai_path": AI_PATH}]}), encoding="utf-8")
        dst_ip = plan.hosts["R7"].ip
        (work / "ospf.txt").write_text(trace_for(plan, ["R1", "R3", "R5", "R7"], dst_ip), encoding="utf-8")
        (work / "ai.txt").write_text(trace_for(plan, AI_PATH, dst_ip), encoding="utf-8")

        def verify(protocol, ai, trace):
            args = argparse.Namespace(protocol=protocol, ai=ai, trace=str(work / trace), out=str(work))
            return cli.verify(args, cfg)

        self.assertEqual(verify("ospf", False, "ospf.txt"), 0)
        self.assertEqual(verify("ospf", False, "ai.txt"), 1)
        self.assertEqual(verify("ospf", True, "ai.txt"), 0)
        self.assertEqual(verify("rip", False, "ospf.txt"), 0)


class CliExportTests(unittest.TestCase):
    """`export --no-ai` must build the baselines without importing the model stack."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("pt_cli_export", ROOT / "scripts" / "packet_tracer.py")
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)
        cls.cfg = load_config()
        cls.plan = build_plan(sample_graph())

    def export(self, work, **overrides):
        args = argparse.Namespace(**{"topology": None, "pair": None, "out": str(work), "no_ai": True, **overrides})
        return self.cli.export(args, self.cfg)

    def test_baseline_only_export_needs_no_model(self):
        work = tmp_dir()
        self.assertEqual(self.export(work), 0)
        for protocol in PROTOCOLS:
            self.assertTrue((work / f"build_{protocol}.js").is_file())
            self.assertTrue((work / "configs" / protocol / "R1.txt").is_file())
        self.assertFalse((work / "ai_routes.js").exists())
        self.assertFalse((work / "ai_routes_undo.js").exists())
        manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["baseline_only"])
        self.assertEqual(manifest["pairs"], [])
        self.assertIn("baseline-only", (work / "GUIDE.md").read_text(encoding="utf-8"))

        dst_ip = self.plan.hosts["R7"].ip
        (work / "trace.txt").write_text(trace_for(self.plan, ["R1", "R3", "R5", "R7"], dst_ip), encoding="utf-8")
        self.assertEqual(self.cli.verify(argparse.Namespace(protocol="ospf", ai=False, trace=str(work / "trace.txt"),
                                                           out=str(work)), self.cfg), 0)

    def test_no_ai_and_pair_are_rejected(self):
        with self.assertRaises(PacketTracerError):
            self.export(tmp_dir(), pair=[["R1", "R7"]])

    def test_verify_ai_on_a_baseline_only_export_says_to_re_export(self):
        work = tmp_dir()
        self.assertEqual(self.export(work), 0)
        with self.assertRaisesRegex(PacketTracerError, "baseline-only"):
            self.cli.verify(argparse.Namespace(protocol="ospf", ai=True, trace=str(work / "missing.txt"),
                                              out=str(work)), self.cfg)


@unittest.skipIf(NODE is None, "Node.js not installed")
class GeneratedScriptTests(unittest.TestCase):
    """Run the generated PTBuilder JavaScript against the PT API mock."""

    @classmethod
    def setUpClass(cls):
        cls.graph = sample_graph()
        cls.plan = build_plan(cls.graph)

    def run_mock(self, scripts: dict[str, str], env=None) -> dict:
        work = tmp_dir()
        files = []
        for name, text in scripts.items():
            (work / name).write_text(text, encoding="utf-8")
            files.append(str(work / name))
        proc = subprocess.run([NODE, str(MOCK), *files], capture_output=True, text=True, check=True,
                              env={**os.environ, **(env or {})})
        return json.loads(proc.stdout)

    def recorded(self, state) -> dict[str, list[str]]:
        return {r: [c for c, _ in state["devices"][r]["commands"] if c not in ("!", "end", "write memory")]
                for r in self.plan.routers}

    def test_build_creates_and_configures_everything(self):
        state = self.run_mock({"build.js": build_script(self.plan, "ospf", configs(self.plan, "ospf"))})
        self.assertIn(" 0 failed", state["messages"][-1]["text"])
        self.assertEqual(set(state["devices"]), set(self.plan.routers) | {h.name for h in self.plan.hosts.values()})
        self.assertEqual(len(state["links"]), len(self.plan.cables))
        for router in self.plan.routers:
            dev = state["devices"][router]
            self.assertTrue(dev["booted"])
            self.assertEqual(dev["commands"][0], ["!", "global"])
            self.assertEqual(dev["commands"][-1], ["write memory", "enable"])
        for host in self.plan.hosts.values():
            self.assertEqual(state["devices"][host.name]["ports"]["FastEthernet0"]["ip"], host.ip)
            self.assertEqual(state["devices"][host.name]["gateway"], host.gateway)
        sim = RoutingSimulation(self.plan, self.recorded(state))
        self.assertEqual(sim.errors, [])
        self.assertIn(ospf_route_from_config(self.graph, "R1", "R7", load_config()).path, sim.paths("R1", "R7"))

    def test_ai_and_undo_scripts_change_the_live_path(self):
        routes = merge_routes(self.plan, [AI_PATH])
        add = routes_script("ai", {r: static_route_lines(x) for r, x in routes.items()}, "")
        undo = routes_script("undo", {r: static_route_lines(x, remove=True) for r, x in routes.items()}, "")
        build = build_script(self.plan, "ospf", configs(self.plan, "ospf"))
        state = self.run_mock({"build.js": build, "ai.js": add})
        self.assertEqual(RoutingSimulation(self.plan, self.recorded(state)).paths("R1", "R7"), {tuple(AI_PATH)})
        state = self.run_mock({"build.js": build, "ai.js": add, "undo.js": undo})
        self.assertEqual(RoutingSimulation(self.plan, self.recorded(state)).paths("R1", "R7"),
                         {("R1", "R3", "R5", "R7")})

    def test_failures_are_reported_not_thrown(self):
        build = build_script(self.plan, "rip", configs(self.plan, "rip"))
        state = self.run_mock({"build.js": build}, env={"PT_MOCK_FAIL_LINKS": "1"})
        self.assertIn(f"{len(self.plan.cables)} failed", state["messages"][-1]["text"])
        state = self.run_mock({"a.js": build, "b.js": build})
        self.assertIn("already exists", state["messages"][-1]["detail"])


if __name__ == "__main__":
    unittest.main()
