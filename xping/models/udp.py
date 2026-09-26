"""UDP probe result models (xping udp)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict

OPEN, CLOSED, NO_RESPONSE = "open", "closed", "no-response"


@dataclass
class UdpAttempt:
    seq: int
    state: str  # "open" (a reply came back) | "closed" (ICMP port unreachable) | "no-response"
    rtt_ms: float | None = None
    reply_bytes: int = 0
    detail: str = ""

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class UdpResult:
    host: str
    port: int
    ip: str | None = None
    probe: str = "empty"  # payload sent: dns | ntp | snmp | hex | empty
    attempts: list[UdpAttempt] = field(default_factory=list)
    error: str | None = None

    @property
    def state(self) -> str:
        """open if any attempt got a reply; closed if the host refused; else
        no-response (UDP cannot tell "open but silent" from "filtered")."""
        states = {a.state for a in self.attempts}
        if OPEN in states:
            return OPEN
        if CLOSED in states:
            return CLOSED
        return NO_RESPONSE

    @property
    def replies(self) -> int:
        return sum(1 for a in self.attempts if a.state == OPEN)

    @property
    def avg_rtt_ms(self) -> float:
        rtts = [a.rtt_ms for a in self.attempts if a.state == OPEN and a.rtt_ms is not None]
        return sum(rtts) / len(rtts) if rtts else -1.0

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
