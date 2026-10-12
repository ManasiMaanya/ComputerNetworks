"""Physical and IP plan for building a project topology in Packet Tracer.

Hardware choice
---------------
Every topology node becomes a **Cisco 3560-24PS multilayer switch** running
as a router (``ip routing`` plus ``no switchport`` routed ports), and each
gets one **PC-PT** host on its LAN. The 3560 has 24 built-in FastEthernet
ports, so any node with up to 23 links fits without installing modules.
Stock PT routers (1941/2911/ISR4331) have only 2-3 Ethernet ports - the
sample topology's R5 needs 4 links plus a LAN - and adding ports to them
means scripted module installs and serial links, which are the least
reliable parts of PT's scripting interface.

Ports and cables
----------------
* Links use ``FastEthernet0/1``, ``0/2``, ... on each device, in the order
  of the device's neighbours (sorted by name). Switch-to-switch cables are
  copper cross-over.
* The LAN uses ``FastEthernet0/24``, cabled straight-through to the PC's
  ``FastEthernet0``.

Addressing
----------
* Link ``i`` (edges in graph order) gets the /30 ``10.0.<i // 64>.<(i % 64) * 4>``;
  the endpoint whose name sorts first takes ``.1``, the other ``.2``.
* Node ``n`` (1-based, graph order) gets LAN ``192.168.<n>.0/24``: the
  router is ``.1`` and its PC ``.10`` (gateway ``.1``).
* OSPF interface cost on a link = the link's ``delay`` rounded to an
  integer (min 1), so PT's OSPF optimizes the same metric as the project's
  OSPF-like(delay) baseline.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from . import PacketTracerError

ROUTER_MODEL = "3560-24PS"
ROUTER_TYPE = 16  # PT device type: multilayer switch
HOST_MODEL = "PC-PT"
HOST_TYPE = 8  # PT device type: PC
HOST_PORT = "FastEthernet0"
LAN_PORT = "FastEthernet0/24"
MAX_LINK_PORTS = 23

#: PT link-type ids (``LogicalWorkspace.createLink``).
CABLE_TYPES = {"straight": 8100, "cross": 8101}


@dataclass(frozen=True)
class Interface:
    device: str
    port: str
    ip: str
    prefixlen: int
    peer: str | None  # neighbouring router, or None for the LAN port
    ospf_cost: int = 1

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Interface(f"{self.ip}/{self.prefixlen}").network

    @property
    def mask(self) -> str:
        return str(self.network.netmask)


@dataclass(frozen=True)
class Cable:
    a_device: str
    a_port: str
    b_device: str
    b_port: str
    kind: str  # key of CABLE_TYPES


@dataclass(frozen=True)
class Host:
    name: str
    router: str
    ip: str
    prefixlen: int
    gateway: str

    @property
    def mask(self) -> str:
        return str(ipaddress.IPv4Network(f"0.0.0.0/{self.prefixlen}").netmask)


@dataclass
class NetworkPlan:
    routers: list[str]
    hostnames: dict[str, str]
    interfaces: dict[str, list[Interface]]
    cables: list[Cable]
    hosts: dict[str, Host]  # router -> its PC
    positions: dict[str, tuple[int, int]]  # every device, routers and PCs
    _ip_owner: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for ifaces in self.interfaces.values():
            for iface in ifaces:
                self._ip_owner[iface.ip] = iface.device
        for host in self.hosts.values():
            self._ip_owner[host.ip] = host.name

    def lan(self, router: str) -> Interface:
        return next(i for i in self.interfaces[router] if i.peer is None)

    def link_interface(self, router: str, neighbor: str) -> Interface:
        for iface in self.interfaces[router]:
            if iface.peer == neighbor:
                return iface
        raise PacketTracerError(f"'{router}' has no link to '{neighbor}'")

    def lan_network(self, router: str) -> ipaddress.IPv4Network:
        return self.lan(router).network

    def owner_of_ip(self, ip: str) -> str | None:
        return self._ip_owner.get(ip)

    def router_of(self, device: str) -> str | None:
        """Router a device belongs to (itself for a router, its gateway router for a PC)."""
        if device in self.interfaces:
            return device
        for router, host in self.hosts.items():
            if host.name == device:
                return router
        return None


def _hostname(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(name)).strip("-")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"R-{cleaned}" if cleaned else "R"
    return cleaned[:63]


def _layout(graph: nx.Graph, nodes: list[Any]) -> dict[str, tuple[int, int]]:
    raw = nx.spring_layout(graph, seed=7)
    xs = [raw[n][0] for n in nodes]
    ys = [raw[n][1] for n in nodes]

    def scale(v: float, lo: float, hi: float, out_lo: int, out_hi: int) -> int:
        return int(out_lo + (v - lo) / ((hi - lo) or 1.0) * (out_hi - out_lo))

    positions: dict[str, tuple[int, int]] = {}
    for n in nodes:
        x = scale(raw[n][0], min(xs), max(xs), 150, 950)
        y = scale(raw[n][1], min(ys), max(ys), 120, 520)
        positions[str(n)] = (x, y)
    return positions


def build_plan(graph: nx.Graph) -> NetworkPlan:
    """Derive the full PT plan (deterministic) from a project topology graph."""
    if graph.is_directed():
        raise PacketTracerError("Packet Tracer links are bidirectional; directed topologies are not supported")
    nodes = list(graph.nodes())
    if not nodes:
        raise PacketTracerError("topology has no nodes")
    if len(nodes) > 254:
        raise PacketTracerError("at most 254 nodes are supported (one 192.168.<n>.0/24 LAN each)")
    names = [str(n) for n in nodes]
    if len(set(names)) != len(names):
        raise PacketTracerError("node names must be unique as strings")
    hostnames = {str(n): _hostname(n) for n in nodes}
    if len(set(hostnames.values())) != len(hostnames):
        raise PacketTracerError("node names collide after conversion to IOS hostnames")
    host_names = {f"PC-{hostnames[str(n)]}" for n in nodes}
    if host_names & set(names):
        raise PacketTracerError("a node name collides with a generated PC name (PC-<node>)")

    for n in nodes:
        if graph.degree(n) > MAX_LINK_PORTS:
            raise PacketTracerError(
                f"node '{n}' has {graph.degree(n)} links; a {ROUTER_MODEL} has {MAX_LINK_PORTS} free ports"
            )

    # Port numbering: neighbours of each node sorted by name.
    port_of: dict[tuple[str, str], str] = {}
    for n in nodes:
        for idx, nb in enumerate(sorted(graph.neighbors(n), key=str), start=1):
            port_of[(str(n), str(nb))] = f"FastEthernet0/{idx}"

    interfaces: dict[str, list[Interface]] = {str(n): [] for n in nodes}
    cables: list[Cable] = []
    for i, (u, v, data) in enumerate(graph.edges(data=True)):
        a, b = sorted((str(u), str(v)))
        if i >= 64 * 256:
            raise PacketTracerError("too many links for the 10.0.0.0/16 link address pool")
        base = ipaddress.IPv4Address(f"10.0.{i // 64}.{(i % 64) * 4}")
        cost = max(1, min(65535, int(round(float(data["delay"])))))
        interfaces[a].append(Interface(a, port_of[(a, b)], str(base + 1), 30, b, cost))
        interfaces[b].append(Interface(b, port_of[(b, a)], str(base + 2), 30, a, cost))
        cables.append(Cable(a, port_of[(a, b)], b, port_of[(b, a)], "cross"))

    hosts: dict[str, Host] = {}
    for idx, n in enumerate(nodes, start=1):
        name = str(n)
        lan_ip = f"192.168.{idx}.1"
        interfaces[name].append(Interface(name, LAN_PORT, lan_ip, 24, None))
        host = Host(f"PC-{hostnames[name]}", name, f"192.168.{idx}.10", 24, lan_ip)
        hosts[name] = host
        cables.append(Cable(name, LAN_PORT, host.name, HOST_PORT, "straight"))
    for ifaces in interfaces.values():
        ifaces.sort(key=lambda i: int(i.port.rsplit("/", 1)[1]))

    positions = _layout(graph, nodes)
    cx = sum(x for x, _ in positions.values()) / len(positions)
    cy = sum(y for _, y in positions.values()) / len(positions)
    for name, host in hosts.items():
        x, y = positions[name]
        dx, dy = x - cx, y - cy
        norm = (dx * dx + dy * dy) ** 0.5 or 1.0
        positions[host.name] = (int(x + 90 * dx / norm), int(y + 90 * dy / norm))

    return NetworkPlan(
        routers=[str(n) for n in nodes],
        hostnames=hostnames,
        interfaces=interfaces,
        cables=cables,
        hosts=hosts,
        positions=positions,
    )
