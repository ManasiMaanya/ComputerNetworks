"""IOS configuration for the Packet Tracer build.

Two baseline routing modes mirror the project's baselines:

* ``"rip"`` - RIPv2 on every interface: PT picks fewest-hop paths
  (RIP-like baseline).
* ``"ospf"`` - single-area OSPF with interface cost = link delay: PT
  picks lowest-delay paths (OSPF-like(delay) baseline).

The AI recommendation is applied on top of either baseline as **static
routes** along the recommended path (administrative distance 1 beats
OSPF's 110 and RIP's 120). Routes are installed for the destination LAN
hop by hop along the path and for the source LAN along the reverse path,
so both ``tracert`` and replies follow it. Static routing is per
destination, so two recommended paths that would need different next hops
toward the same LAN on the same router conflict; that is reported rather
than silently resolved.
"""

from __future__ import annotations

from typing import Any

from . import PacketTracerError
from .plan import NetworkPlan

PROTOCOLS = ("ospf", "rip")


def _classful(ip: str) -> str:
    first = int(ip.split(".")[0])
    octets = ip.split(".")
    if first < 128:
        return f"{octets[0]}.0.0.0"
    if first < 192:
        return f"{octets[0]}.{octets[1]}.0.0"
    return f"{octets[0]}.{octets[1]}.{octets[2]}.0"


def router_config(plan: NetworkPlan, router: str, protocol: str) -> list[str]:
    """Full config for one router (IOS lines, indented as ``show run`` would)."""
    if protocol not in PROTOCOLS:
        raise PacketTracerError(f"unknown protocol '{protocol}'; expected one of {PROTOCOLS}")
    lines = [f"hostname {plan.hostnames[router]}", "ip routing"]
    for iface in plan.interfaces[router]:
        peer = f"link to {iface.peer}" if iface.peer else f"LAN {plan.hosts[router].name}"
        lines += [
            f"interface {iface.port}",
            f" description {peer}",
            " no switchport",
            f" ip address {iface.ip} {iface.mask}",
        ]
        if protocol == "ospf" and iface.peer is not None:
            lines.append(f" ip ospf cost {iface.ospf_cost}")
        lines += [" no shutdown", " exit"]
    if protocol == "ospf":
        idx = plan.routers.index(router) + 1
        lines += ["router ospf 1", f" router-id 10.255.{idx // 256}.{idx % 256}"]
        for iface in plan.interfaces[router]:
            net = iface.network
            lines.append(f" network {net.network_address} {net.hostmask} area 0")
        lines.append(" exit")
    else:
        lines += ["router rip", " version 2", " no auto-summary"]
        for net in sorted({_classful(i.ip) for i in plan.interfaces[router]}):
            lines.append(f" network {net}")
        lines.append(" exit")
    return lines


def path_static_routes(plan: NetworkPlan, path: list[Any]) -> dict[str, list[tuple[str, str, str]]]:
    """``(prefix, mask, next_hop)`` routes per router that pin traffic to ``path``.

    Covers the destination LAN along the path and the source LAN along the
    reverse path.
    """
    nodes = [str(n) for n in path]
    if len(nodes) < 2:
        raise PacketTracerError("a path needs at least two routers")
    if len(set(nodes)) != len(nodes):
        raise PacketTracerError("path visits a router twice")
    routes: dict[str, list[tuple[str, str, str]]] = {}
    for seq in (nodes, nodes[::-1]):
        dst_net = plan.lan_network(seq[-1])
        for here, nxt in zip(seq, seq[1:]):
            next_hop = plan.link_interface(nxt, here).ip
            routes.setdefault(here, []).append(
                (str(dst_net.network_address), str(dst_net.netmask), next_hop)
            )
    return routes


def merge_routes(
    plan: NetworkPlan, paths: list[list[Any]]
) -> dict[str, list[tuple[str, str, str]]]:
    """Static routes for several paths; raises on a per-destination conflict."""
    merged: dict[str, dict[tuple[str, str], str]] = {}
    for path in paths:
        for router, routes in path_static_routes(plan, path).items():
            table = merged.setdefault(router, {})
            for prefix, mask, nh in routes:
                existing = table.get((prefix, mask))
                if existing is not None and existing != nh:
                    raise PacketTracerError(
                        f"conflicting static routes on {router} for {prefix}/{mask}: next hop "
                        f"{existing} vs {nh} - destination-based routing cannot follow both paths"
                    )
                table[(prefix, mask)] = nh
    return {r: [(p, m, nh) for (p, m), nh in t.items()] for r, t in merged.items()}


def static_route_lines(routes: list[tuple[str, str, str]], remove: bool = False) -> list[str]:
    prefix = "no " if remove else ""
    return [f"{prefix}ip route {p} {m} {nh}" for p, m, nh in routes]
