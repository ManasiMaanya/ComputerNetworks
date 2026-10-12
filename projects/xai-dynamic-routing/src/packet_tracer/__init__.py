"""Cisco Packet Tracer integration: build the topology in PT and verify paths.

* plan       - devices, ports, cables, IP addressing and layout.
* ios        - IOS configuration (RIP / OSPF baselines, AI static routes).
* ptbuilder  - JavaScript for PT's Script Engine (run it from the PTBuilder "Builder Code
               Editor") that builds and configures the network.
* routesim   - offline simulation of the generated IOS configs, used to predict the path PT
               will forward on.
* tracert    - parse `tracert` output copied from a PT PC and check it against the prediction.
"""

from ..errors import RoutingProjectError


class PacketTracerError(RoutingProjectError):
    """Topology or request the Packet Tracer integration cannot handle."""
