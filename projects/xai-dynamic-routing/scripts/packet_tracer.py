"""Cisco Packet Tracer integration (Phase 7 testbed): build the network in PT and verify paths.

    python scripts/packet_tracer.py export                       # sample topology, demo pairs
    python scripts/packet_tracer.py export --pair R1 R7 --pair R3 R6
    python scripts/packet_tracer.py export --topology data/raw/topology-zoo/gml/gml/Abilene.gml
    python scripts/packet_tracer.py verify --protocol ospf --trace trace.txt
    python scripts/packet_tracer.py verify --protocol ospf --ai --trace trace.txt

`export` writes, under outputs/packet_tracer/ (or --out):
    build_ospf.js / build_rip.js        PTBuilder scripts that build + configure the whole network
    ai_routes.js / ai_routes_undo.js    add / remove static routes pinning pairs to the AI's path
    configs/<protocol>/<router>.txt     the same IOS configs, for manual pasting
    manifest.json, GUIDE.md             AI paths, expected tracert paths, step-by-step guide
Without --pair it picks up to 3 pairs where the AI's path differs from every OSPF path.

`verify` checks tracert output copied from a PT PC against the router path the generated configs
should produce (src/packet_tracer/routesim.py simulates those exact IOS lines).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import banner, rel, run
from src.config import load_config, output_dir, project_dir, resolve_input_path, resolve_path
from src.packet_tracer import PacketTracerError
from src.packet_tracer.ios import PROTOCOLS, merge_routes, router_config, static_route_lines
from src.packet_tracer.plan import ROUTER_MODEL, build_plan
from src.packet_tracer.ptbuilder import build_script, routes_script
from src.packet_tracer.routesim import RoutingSimulation
from src.packet_tracer.tracert import check_trace
from src.routing.recommender import RouteRecommender
from src.topology.load import load_topology

MAX_DEMO_PAIRS = 3


def _configs(plan, protocol, ai_routes=None) -> dict[str, list[str]]:
    configs = {r: router_config(plan, r, protocol) for r in plan.routers}
    for router, routes in (ai_routes or {}).items():
        configs[router] = configs[router] + static_route_lines(routes)
    return configs


def _sim(plan, protocol, ai_routes=None) -> RoutingSimulation:
    sim = RoutingSimulation(plan, _configs(plan, protocol, ai_routes))
    if sim.errors:
        raise PacketTracerError("generated configs failed the offline check: " + "; ".join(sim.errors))
    return sim


def _ai_path(graph, recommender, src, dst) -> list[str]:
    return [str(n) for n in recommender.recommend(graph, src, dst).path]


def _pick_demo_pairs(graph, plan, recommender) -> list[tuple[str, str, list[str]]]:
    """Up to MAX_DEMO_PAIRS pairs where the AI path differs from every OSPF path, conflict-free."""
    ospf = _sim(plan, "ospf")
    chosen: list[tuple[str, str, list[str]]] = []
    for src in plan.routers:
        for dst in plan.routers:
            if src == dst or len(chosen) >= MAX_DEMO_PAIRS or any({src, dst} == {s, d} for s, d, _ in chosen):
                continue
            path = _ai_path(graph, recommender, src, dst)
            if tuple(path) in ospf.paths(src, dst):
                continue
            try:
                merge_routes(plan, [p for _, _, p in chosen] + [path])
            except PacketTracerError:
                continue
            chosen.append((src, dst, path))
    return chosen


def _fmt(paths) -> str:
    return " or ".join(" -> ".join(p) for p in sorted(paths))


def export(args, cfg) -> int:
    topo = resolve_input_path(args.topology) if args.topology else resolve_path(cfg["sample_topology"])
    graph = load_topology(topo, cfg)
    plan = build_plan(graph)
    recommender = RouteRecommender.load(project_dir(cfg, "models_dir"), cfg)

    pairs = ([(s, d, _ai_path(graph, recommender, s, d)) for s, d in args.pair] if args.pair
             else _pick_demo_pairs(graph, plan, recommender))
    ai_routes = merge_routes(plan, [p for _, _, p in pairs]) if pairs else {}
    sims = {p: _sim(plan, p) for p in PROTOCOLS}
    ai_sims = {p: _sim(plan, p, ai_routes) for p in PROTOCOLS}

    out = resolve_input_path(args.out) if args.out else output_dir(cfg, "packet_tracer")
    out.mkdir(parents=True, exist_ok=True)
    for protocol in PROTOCOLS:
        configs = _configs(plan, protocol)
        (out / f"build_{protocol}.js").write_text(build_script(plan, protocol, configs), encoding="utf-8")
        cfg_dir = out / "configs" / protocol
        cfg_dir.mkdir(parents=True, exist_ok=True)
        for router, lines in configs.items():
            text = "\n".join(["enable", "configure terminal", *lines, "end", "write memory"]) + "\n"
            (cfg_dir / f"{plan.hostnames[router]}.txt").write_text(text, encoding="utf-8")
    if ai_routes:
        add = {r: static_route_lines(x) for r, x in ai_routes.items()}
        undo = {r: static_route_lines(x, remove=True) for r, x in ai_routes.items()}
        note = "AI paths: " + "; ".join(" -> ".join(p) for _, _, p in pairs)
        (out / "ai_routes.js").write_text(routes_script("XAI routing - apply AI routes", add, note), encoding="utf-8")
        (out / "ai_routes_undo.js").write_text(routes_script("XAI routing - remove AI routes", undo, note),
                                               encoding="utf-8")
    else:
        for stale in ("ai_routes.js", "ai_routes_undo.js"):
            (out / stale).unlink(missing_ok=True)

    manifest = {
        "topology": rel(topo),
        "router_model": ROUTER_MODEL,
        "pairs": [{
            "src": s, "dst": d, "src_pc": plan.hosts[s].name, "dst_ip": plan.hosts[d].ip, "ai_path": path,
            "expected": {
                **{p: sorted(list(x) for x in sims[p].paths(s, d)) for p in PROTOCOLS},
                **{f"{p}+ai": sorted(list(x) for x in ai_sims[p].paths(s, d)) for p in PROTOCOLS},
            },
        } for s, d, path in pairs],
        "addresses": {
            **{r: {i.port: f"{i.ip}/{i.prefixlen}" for i in plan.interfaces[r]} for r in plan.routers},
            **{h.name: {"FastEthernet0": f"{h.ip}/{h.prefixlen}", "gateway": h.gateway} for h in plan.hosts.values()},
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "GUIDE.md").write_text(_guide(manifest), encoding="utf-8")

    banner("Packet Tracer export")
    print(f"topology: {rel(topo)}  ({len(plan.routers)} routers as {ROUTER_MODEL}, {len(plan.hosts)} PCs)")
    print("offline check of the generated IOS configs: OK (no parse/addressing/routing errors)")
    for entry in manifest["pairs"]:
        print(f"\n{entry['src']} -> {entry['dst']}  (tracert {entry['dst_ip']} from {entry['src_pc']})")
        for mode, paths in entry["expected"].items():
            print(f"  {mode:9s} {_fmt(tuple(p) for p in paths)}")
    if not pairs:
        print("\nno pair found where the AI path differs from OSPF's, so no ai_routes.js was written;"
              "\npin one anyway with --pair SRC DST")
    print(f"\nwritten to {rel(out)}  (start with GUIDE.md)")
    return 0


def _guide(manifest) -> str:
    lines = [
        "# Packet Tracer guide",
        "",
        f"Routers are **{manifest['router_model']}** multilayer switches running as routers (`ip routing`,",
        "routed ports); each has one PC on `FastEthernet0/24`. See `src/packet_tracer/plan.py` for why.",
        "",
        "## One-time setup",
        "",
        "1. Download `Builder.pts` from https://github.com/kimmknight/PTBuilder",
        "2. Packet Tracer: **Extensions > Scripting > Configure PT Script Modules > Add...** and pick `Builder.pts`.",
        "",
        "## Build",
        "",
        "1. **File > New** (the script refuses to run if devices with the same names exist).",
        "2. **Extensions > Builder Code Editor**, paste all of `build_ospf.js` (or `build_rip.js`), click **Run**.",
        "3. A message box reports how many steps succeeded and lists any failures.",
        "4. Let OSPF/RIP converge: click **Fast Forward Time** (bottom-left, Realtime mode) a few times,",
        "   or wait about a minute.",
        "",
        "If a script fails, each router's config is also in `configs/<protocol>/<router>.txt`:",
        "open the router's CLI tab and paste it.",
        "",
        "Troubleshooting on a router's CLI: `show ip interface brief` (routed ports up, addressed?),",
        "`show ip route` (OSPF `O` / RIP `R` / static `S` routes present?), `show running-config`",
        "(`ip routing` present? it is what lets a 3560 forward between routed ports).",
        "",
        "## Test a path",
        "",
        "On the source PC: **Desktop > Command Prompt**, run `tracert <destination PC IP>`,",
        "copy the whole output into a text file, then:",
        "",
        "```",
        "python scripts/packet_tracer.py verify --protocol ospf --trace trace.txt",
        "python scripts/packet_tracer.py verify --protocol ospf --ai --trace trace.txt   # after ai_routes.js",
        "```",
        "",
        "## AI routes",
        "",
    ]
    if manifest["pairs"]:
        lines += ["Paste `ai_routes.js` into the Builder Code Editor and Run: static routes pin the pairs",
                  "below to the AI's path. `ai_routes_undo.js` removes them again.", ""]
    else:
        lines += ["No pair was found where the AI's path differs from OSPF's, so no `ai_routes.js` was",
                  "written. Re-run `export --pair SRC DST` to pin a pair anyway.", ""]
    for e in manifest["pairs"]:
        lines += [f"### {e['src']} -> {e['dst']}: `tracert {e['dst_ip']}` on {e['src_pc']}", "",
                  "| Configuration | Expected router path |", "|---|---|"]
        lines += [f"| {mode} | {_fmt(tuple(p) for p in paths)} |" for mode, paths in e["expected"].items()]
        lines.append("")
    lines += ["## Addressing", "", "| Device | Interface | Address |", "|---|---|---|"]
    for device, ports in manifest["addresses"].items():
        lines += [f"| {device} | {port} | {addr} |" for port, addr in ports.items()]
    return "\n".join(lines) + "\n"


def verify(args, cfg) -> int:
    out = resolve_input_path(args.out) if args.out else output_dir(cfg, "packet_tracer")
    manifest_path = out / "manifest.json"
    if not manifest_path.is_file():
        raise PacketTracerError(f"{manifest_path} not found; run `python scripts/packet_tracer.py export` first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan = build_plan(load_topology(resolve_input_path(manifest["topology"]), cfg))
    ai_routes = merge_routes(plan, [e["ai_path"] for e in manifest["pairs"]]) if args.ai else None
    sim = _sim(plan, args.protocol, ai_routes)
    trace_file = Path(args.trace)
    if args.trace != "-" and not trace_file.is_file():
        raise PacketTracerError(f"trace file not found: {trace_file}")
    text = sys.stdin.read() if args.trace == "-" else trace_file.read_text(encoding="utf-8")

    result = check_trace(plan, text, set())
    if result.target is None:
        raise PacketTracerError("could not find the tracert target address in the output")
    dst_owner = plan.owner_of_ip(result.target)
    dst = plan.router_of(dst_owner) if dst_owner else None
    src = result.routers[0] if result.routers else None
    if dst is None or src is None:
        raise PacketTracerError("cannot tell source/destination: the first hop must be the source PC's gateway "
                                "and the target must be a PC or router address from this plan")
    expected = sim.paths(src, dst)
    result = check_trace(plan, text, expected)

    mode = args.protocol + ("+ai" if args.ai else "")
    print(f"configuration: {mode}   trace: {src} -> {dst} ({result.target})")
    print(f"observed path: {' -> '.join(r or '?' for r in result.routers)}"
          f"{'' if result.reached else '   (destination NOT reached)'}")
    print(f"expected path: {_fmt(expected)}")
    if result.unknown_ips:
        print(f"unknown hop address(es): {', '.join(result.unknown_ips)} - not in this plan")
    if result.ok:
        print("MATCH" + (" (timed-out hops treated as wildcards)" if None in result.routers else ""))
        return 0
    print("MISMATCH")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None, help="config JSON (default: configs/default.json)")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="write PTBuilder scripts, IOS configs and the guide")
    exp.add_argument("--topology", default=None, help="topology file (default: sample topology)")
    exp.add_argument("--pair", nargs=2, action="append", metavar=("SRC", "DST"),
                     help="pair to pin to the AI path (repeatable; default: up to 3 pairs where AI != OSPF)")
    exp.add_argument("--out", default=None, help="output folder (default: outputs/packet_tracer)")
    ver = sub.add_parser("verify", help="check tracert output from a PT PC")
    ver.add_argument("--protocol", choices=PROTOCOLS, required=True)
    ver.add_argument("--ai", action="store_true", help="ai_routes.js has been applied")
    ver.add_argument("--trace", required=True, help="file with tracert output ('-' = stdin)")
    ver.add_argument("--out", default=None, help="folder holding manifest.json (default: outputs/packet_tracer)")
    args = parser.parse_args()
    cfg = load_config(args.config)
    return export(args, cfg) if args.command == "export" else verify(args, cfg)


if __name__ == "__main__":
    run(main)
