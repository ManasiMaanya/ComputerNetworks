"""Offline simulation of the generated IOS configs (no Packet Tracer needed).

Parses the exact command lines that are pushed to each device - not the
plan objects they were generated from - and computes the forwarding paths
IOS would use, so tests (and ``scripts/packet_tracer.py verify``) can check
what PT should do:

* interfaces: ``no switchport``, ``ip address``, ``ip ospf cost``,
  ``shutdown`` / ``no shutdown``; a 3560 port needs ``no switchport``
  before it accepts an address, and the device needs ``ip routing`` to
  forward;
* OSPF: ``network <addr> <wildcard> area 0``; path cost = sum of outgoing
  interface costs (default 1, i.e. FastEthernet with the 100 Mb/s
  reference bandwidth);
* RIPv2: classful ``network`` statements; metric = hop count (max 15);
* static routes: ``ip route <prefix> <mask> <next-hop>`` / ``no ip route``;
* route choice per destination prefix: connected (AD 0) > static (1) >
  OSPF (110) > RIP (120); equal-cost OSPF/RIP next hops are all kept
  (ECMP), so a destination can have several valid paths.

Scope: exact-prefix lookups only (the plan never creates overlapping or
summary prefixes), single OSPF area, no redistribution.
"""

from __future__ import annotations

import heapq
import ipaddress
from dataclasses import dataclass, field

from . import PacketTracerError
from .plan import NetworkPlan

AD = {"connected": 0, "static": 1, "ospf": 110, "rip": 120}
RIP_INFINITY = 16


@dataclass
class _Iface:
    name: str
    routed: bool = False
    address: ipaddress.IPv4Interface | None = None
    ospf_cost: int | None = None
    shutdown: bool = False


@dataclass
class _Device:
    name: str
    ip_routing: bool = False
    ifaces: dict[str, _Iface] = field(default_factory=dict)
    ospf_networks: list[tuple[int, int]] = field(default_factory=list)  # (addr, wildcard) as ints
    rip_networks: set[str] = field(default_factory=set)
    rip: bool = False
    ospf: bool = False
    statics: dict[str, str] = field(default_factory=dict)  # prefix (cidr) -> next-hop ip
    errors: list[str] = field(default_factory=list)

    def up(self) -> list[_Iface]:
        return [i for i in self.ifaces.values() if i.address is not None and not i.shutdown]


def _classful(ip: ipaddress.IPv4Address) -> ipaddress.IPv4Network:
    first = int(str(ip).split(".")[0])
    plen = 8 if first < 128 else 16 if first < 192 else 24
    return ipaddress.IPv4Network(f"{ip}/{plen}", strict=False)


def parse_config(name: str, lines: list[str]) -> _Device:
    dev = _Device(name)
    ctx: tuple[str, str | None] = ("global", None)
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        words = line.split()
        low = [w.lower() for w in words]
        if low[0] in ("exit", "end"):
            ctx = ("global", None)
            continue
        if low[0] == "interface":
            iface = dev.ifaces.setdefault(words[1], _Iface(words[1]))
            ctx = ("iface", iface.name)
            continue
        if low[:2] == ["router", "ospf"]:
            dev.ospf, ctx = True, ("ospf", None)
            continue
        if low[:2] == ["router", "rip"]:
            dev.rip, ctx = True, ("rip", None)
            continue
        kind = ctx[0]
        if kind == "iface":
            iface = dev.ifaces[ctx[1]]
            if low == ["no", "switchport"]:
                iface.routed = True
            elif low[:2] == ["ip", "address"]:
                if not iface.routed:
                    dev.errors.append(f"{iface.name}: ip address on a switchport (needs 'no switchport')")
                else:
                    iface.address = ipaddress.IPv4Interface(f"{words[2]}/{words[3]}")
            elif low[:3] == ["ip", "ospf", "cost"]:
                iface.ospf_cost = int(words[3])
            elif low == ["shutdown"]:
                iface.shutdown = True
            elif low == ["no", "shutdown"]:
                iface.shutdown = False
            continue
        if kind == "ospf":
            if low[0] == "network" and len(words) >= 5:
                addr = int(ipaddress.IPv4Address(words[1]))
                wild = int(ipaddress.IPv4Address(words[2]))
                dev.ospf_networks.append((addr & ~wild & 0xFFFFFFFF, wild))
            continue
        if kind == "rip":
            if low[0] == "network":
                dev.rip_networks.add(str(_classful(ipaddress.IPv4Address(words[1]))))
            continue
        # global context
        if low[:2] == ["ip", "routing"]:
            dev.ip_routing = True
        elif low[:2] == ["ip", "route"] or low[:3] == ["no", "ip", "route"]:
            remove = low[0] == "no"
            args = words[3:] if remove else words[2:]
            prefix = str(ipaddress.IPv4Network(f"{args[0]}/{args[1]}"))
            if remove:
                dev.statics.pop(prefix, None)
            else:
                dev.statics[prefix] = args[2]
    return dev


@dataclass
class Route:
    source: str
    next_hops: frozenset[str]  # neighbouring device names; empty for connected


class RoutingSimulation:
    """Per-router routing tables computed from parsed configs + the plan's cabling."""

    def __init__(self, plan: NetworkPlan, configs: dict[str, list[str]]) -> None:
        self.plan = plan
        self.devices = {name: parse_config(name, lines) for name, lines in configs.items()}
        self.errors = [f"{d.name}: {e}" for d in self.devices.values() for e in d.errors]
        self._adj = self._adjacencies()
        self._prefixes = self.prefixes()
        self._ospf_cache: dict[str, dict[str, float]] = {}
        self._rip_cache: dict[str, dict[str, int]] = {}
        self.tables = {name: self._table(name) for name in self.devices}

    # -- topology ---------------------------------------------------------
    def _adjacencies(self) -> dict[str, list[tuple[str, _Iface, _Iface]]]:
        """device -> [(neighbour, my iface, their iface)] over cabled, up, same-subnet links."""
        adj: dict[str, list[tuple[str, _Iface, _Iface]]] = {n: [] for n in self.devices}
        for c in self.plan.cables:
            if c.a_device not in self.devices or c.b_device not in self.devices:
                continue
            ia = self.devices[c.a_device].ifaces.get(c.a_port)
            ib = self.devices[c.b_device].ifaces.get(c.b_port)
            if not ia or not ib or ia.address is None or ib.address is None or ia.shutdown or ib.shutdown:
                continue
            if ia.address.network != ib.address.network:
                self.errors.append(f"{c.a_device} {c.a_port} / {c.b_device} {c.b_port}: subnet mismatch")
                continue
            adj[c.a_device].append((c.b_device, ia, ib))
            adj[c.b_device].append((c.a_device, ib, ia))
        return adj

    def _ospf_enabled(self, dev: _Device, iface: _Iface) -> bool:
        if not dev.ospf or iface.address is None:
            return False
        ip = int(iface.address.ip)
        return any((ip & ~wild & 0xFFFFFFFF) == addr for addr, wild in dev.ospf_networks)

    def _rip_enabled(self, dev: _Device, iface: _Iface) -> bool:
        return dev.rip and iface.address is not None and str(_classful(iface.address.ip)) in dev.rip_networks

    def prefixes(self) -> set[str]:
        return {str(i.address.network) for d in self.devices.values() for i in d.up()}

    # -- protocols ----------------------------------------------------------
    def _ospf_distances(self, prefix: str) -> dict[str, float]:
        """Cost from every router to ``prefix`` (Dijkstra on reversed outgoing costs)."""
        dist: dict[str, float] = {}
        heap: list[tuple[float, str]] = []
        for name, dev in self.devices.items():
            for iface in dev.up():
                if str(iface.address.network) == prefix and self._ospf_enabled(dev, iface):
                    cost = iface.ospf_cost or 1
                    if cost < dist.get(name, float("inf")):
                        dist[name] = cost
                        heapq.heappush(heap, (cost, name))
        while heap:
            d, node = heapq.heappop(heap)
            if d > dist.get(node, float("inf")):
                continue
            for nb, mine, theirs in self._adj[node]:
                nb_dev, node_dev = self.devices[nb], self.devices[node]
                if not (self._ospf_enabled(node_dev, mine) and self._ospf_enabled(nb_dev, theirs)):
                    continue
                nd = d + (theirs.ospf_cost or 1)  # neighbour's outgoing interface toward node
                if nd < dist.get(nb, float("inf")):
                    dist[nb] = nd
                    heapq.heappush(heap, (nd, nb))
        return dist

    def _rip_metrics(self, prefix: str) -> dict[str, int]:
        metric: dict[str, int] = {}
        frontier = []
        for name, dev in self.devices.items():
            for iface in dev.up():
                if str(iface.address.network) == prefix and self._rip_enabled(dev, iface):
                    metric[name] = 0
                    frontier.append(name)
        while frontier:
            nxt = []
            for node in frontier:
                for nb, mine, theirs in self._adj[node]:
                    if not (self._rip_enabled(self.devices[node], mine) and self._rip_enabled(self.devices[nb], theirs)):
                        continue
                    m = metric[node] + 1
                    if m < RIP_INFINITY and m < metric.get(nb, RIP_INFINITY):
                        metric[nb] = m
                        nxt.append(nb)
            frontier = nxt
        return metric

    def _table(self, name: str) -> dict[str, Route]:
        dev = self.devices[name]
        table: dict[str, Route] = {}
        for iface in dev.up():
            table[str(iface.address.network)] = Route("connected", frozenset())
        for prefix in self._prefixes:
            if prefix in table:
                continue
            nh_ip = dev.statics.get(prefix)
            if nh_ip is not None:
                nb = self._resolve_next_hop(name, nh_ip)
                if nb is not None:
                    table[prefix] = Route("static", frozenset([nb]))
                    continue
                self.errors.append(f"{name}: static route {prefix} via {nh_ip} is not on a connected subnet")
            ospf = {}
            if dev.ospf:
                if prefix not in self._ospf_cache:
                    self._ospf_cache[prefix] = self._ospf_distances(prefix)
                ospf = self._ospf_cache[prefix]
            if name in ospf:
                hops = frozenset(
                    nb for nb, mine, theirs in self._adj[name]
                    if self._ospf_enabled(dev, mine) and self._ospf_enabled(self.devices[nb], theirs)
                    and nb in ospf and abs((mine.ospf_cost or 1) + ospf[nb] - ospf[name]) < 1e-9
                )
                table[prefix] = Route("ospf", hops)
                continue
            rip = {}
            if dev.rip:
                if prefix not in self._rip_cache:
                    self._rip_cache[prefix] = self._rip_metrics(prefix)
                rip = self._rip_cache[prefix]
            if name in rip:
                hops = frozenset(
                    nb for nb, mine, theirs in self._adj[name]
                    if self._rip_enabled(dev, mine) and self._rip_enabled(self.devices[nb], theirs)
                    and rip.get(nb) == rip[name] - 1
                )
                table[prefix] = Route("rip", hops)
        return table

    def _resolve_next_hop(self, name: str, ip: str) -> str | None:
        addr = ipaddress.IPv4Address(ip)
        for nb, mine, theirs in self._adj[name]:
            if addr in mine.address.network and theirs.address.ip == addr:
                return nb
        return None

    # -- forwarding ---------------------------------------------------------
    def paths(self, src: str, dst: str) -> set[tuple[str, ...]]:
        """Every router path a packet from ``src``'s LAN to ``dst``'s LAN can take.

        Raises :class:`PacketTracerError` on a routing loop, a black hole, or
        a device without ``ip routing``.
        """
        prefix = str(self.plan.lan_network(dst))
        results: set[tuple[str, ...]] = set()

        def walk(node: str, trail: tuple[str, ...]) -> None:
            if node in trail:
                raise PacketTracerError(f"routing loop toward {prefix}: {' -> '.join(trail + (node,))}")
            trail = trail + (node,)
            route = self.tables[node].get(prefix)
            if route is None:
                raise PacketTracerError(f"{node} has no route to {prefix}")
            if route.source == "connected":
                results.add(trail)
                return
            if not self.devices[node].ip_routing:
                raise PacketTracerError(f"{node} has no 'ip routing' and cannot forward")
            for nb in sorted(route.next_hops):
                walk(nb, trail)

        walk(src, ())
        return results

    def route_source(self, router: str, dst: str) -> str | None:
        route = self.tables[router].get(str(self.plan.lan_network(dst)))
        return route.source if route else None
