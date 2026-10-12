"""Export a project graph as a Mininet script (Phase 7, secondary testbed).

One OVS bridge (STP on, no controller) per router plus one host per router; every link becomes a
TCLink with bw = bandwidth (capped at 1000 Mbps, Mininet's TCLink limit), delay = delay ms, and
loss = loss * 100 %. Running the output needs Linux, Mininet, and root; it is not run on Windows.
"""

from __future__ import annotations

import json

import networkx as nx

TCLINK_MAX_MBPS = 1000.0

TEMPLATE = '''#!/usr/bin/env python3
"""Mininet topology exported from {source} by scripts/export_mininet.py.

Run on Linux with Mininet installed:  sudo python3 {filename} [--cli]
Bridges run STP in standalone mode, so no controller is needed. Hosts h<i> attach to router s<i>.
"""

import sys

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.topo import Topo

ROUTERS = {routers}
LINKS = {links}  # (u, v, bw_mbps, delay_ms, loss_percent)


class ExportedTopo(Topo):
    def build(self):
        switches = {{}}
        for i, name in enumerate(ROUTERS, start=1):
            switches[name] = self.addSwitch(f"s{{i}}", stp=True, failMode="standalone")
            host = self.addHost(f"h{{i}}", ip=f"10.0.{{i // 250}}.{{i % 250 + 1}}/16")
            self.addLink(host, switches[name])
        for u, v, bw, delay, loss in LINKS:
            self.addLink(switches[u], switches[v], cls=TCLink, bw=bw, delay=f"{{delay:.3f}}ms", loss=loss)


def main():
    setLogLevel("info")
    net = Mininet(topo=ExportedTopo(), switch=OVSBridge, link=TCLink, controller=None)
    net.start()
    try:
        net.waitConnected()
        net.pingAll()
        if "--cli" in sys.argv:
            CLI(net)
    finally:
        net.stop()


if __name__ == "__main__":
    main()
'''


def mininet_script(graph: nx.Graph, source: str, filename: str) -> tuple[str, dict]:
    routers = sorted(map(str, graph.nodes()))
    links, capped = [], 0
    for u, v, data in sorted(graph.edges(data=True), key=lambda e: (str(e[0]), str(e[1]))):
        bw = float(data["bandwidth"])
        if bw > TCLINK_MAX_MBPS:
            bw, capped = TCLINK_MAX_MBPS, capped + 1
        links.append((str(u), str(v), round(bw, 3), round(float(data["delay"]), 3),
                      round(float(data["loss"]) * 100, 4)))
    text = TEMPLATE.format(source=source, filename=filename, routers=json.dumps(routers),
                           links=repr(links))
    return text, {"routers": len(routers), "links": len(links), "bandwidth_capped": capped}
