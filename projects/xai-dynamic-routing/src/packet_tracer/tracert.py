"""Check ``tracert`` output from a Packet Tracer PC against predicted paths.

A PT PC's Command Prompt prints Windows-style output::

    C:\\>tracert 192.168.7.10

    Tracing route to 192.168.7.10 over a maximum of 30 hops:

      1   0 ms      0 ms      0 ms      192.168.1.1
      2   0 ms      0 ms      0 ms      10.0.0.6
      3   *         *         *         Request timed out.
      4   0 ms      0 ms      0 ms      192.168.7.10

    Trace complete.

Each hop's address is mapped to the device that owns it in the
:class:`~src.packet_tracer.plan.NetworkPlan` (routers answer from one of
their interface addresses, so any interface identifies the router). Hops
that time out become unknowns that match any router.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import PacketTracerError
from .plan import NetworkPlan

_IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_HOP = re.compile(r"^\s*(\d+)\s+(.*)$")


@dataclass
class TraceResult:
    target: str | None
    hops: list[str | None]  # one IP (or None for a timeout) per hop
    routers: list[str | None]  # router per hop before the target (None = unknown)
    reached: bool
    matched: tuple[str, ...] | None  # the expected path it matched, if any
    unknown_ips: list[str]

    @property
    def ok(self) -> bool:
        return self.reached and self.matched is not None and not self.unknown_ips


def parse_tracert(text: str) -> tuple[str | None, list[str | None]]:
    """Return ``(target ip, [hop ip or None, ...])`` from tracert output."""
    target = None
    hops: list[str | None] = []
    started = False
    for line in text.splitlines():
        lower = line.lower()
        if "tracing route to" in lower:
            found = _IP.findall(line)
            target = found[0] if found else None
            started = True
            continue
        if not started and target is None and "tracert" in lower:
            found = _IP.findall(line)
            target = found[-1] if found else target
            continue
        m = _HOP.match(line)
        if not m or not (started or target):
            continue
        ips = _IP.findall(m.group(2))
        hops.append(ips[-1] if ips else None)
    if not hops:
        raise PacketTracerError("no hop lines found - paste the full tracert output")
    return target, hops


def _matches(observed: list[str | None], expected: tuple[str, ...]) -> bool:
    return len(observed) == len(expected) and all(o is None or o == e for o, e in zip(observed, expected))


def check_trace(plan: NetworkPlan, text: str, expected: set[tuple[str, ...]]) -> TraceResult:
    target, hops = parse_tracert(text)
    reached = target is not None and hops[-1] == target
    router_hops = hops[:-1] if reached and plan.owner_of_ip(target) not in plan.interfaces else hops
    routers: list[str | None] = []
    unknown: list[str] = []
    for ip in router_hops:
        if ip is None:
            routers.append(None)
            continue
        owner = plan.owner_of_ip(ip)
        router = plan.router_of(owner) if owner else None
        if router is None:
            unknown.append(ip)
        routers.append(router)
    matched = next((p for p in sorted(expected) if _matches(routers, p)), None)
    return TraceResult(target, hops, routers, reached, matched, unknown)
