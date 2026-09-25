"""Path MTU discovery result model."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict

# IPv4 header (20 bytes) + ICMP echo header (8 bytes) — the overhead added
# on top of the ICMP payload to get the full on-the-wire IP packet size.
ICMP_OVERHEAD_BYTES = 28
# IPv6 header (40 bytes) + ICMPv6 echo header (8 bytes)
ICMPV6_OVERHEAD_BYTES = 48


@dataclass
class MtuResult:
    host: str
    ip: str | None = None
    path_mtu: int | None = None  # full on-the-wire IP packet size, e.g. 1500
    probes: list[dict] = field(default_factory=list)
    method: str = "subprocess"
    overhead: int = ICMP_OVERHEAD_BYTES  # IP + ICMP header bytes (28 IPv4, 48 IPv6)
    error: str | None = None

    @property
    def max_payload(self) -> int | None:
        """Largest unfragmented ICMP payload (path_mtu minus IP/ICMP headers)."""
        return self.path_mtu - self.overhead if self.path_mtu else None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
