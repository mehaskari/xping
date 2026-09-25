"""Traceroute hop model."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class Hop:
    ttl: int
    host: str | None
    ip: str | None
    rtts: list[float] = field(default_factory=list)
    timeout: bool = False
    asn: int | None = None  # origin AS of the hop address (trace --asn)
    as_name: str | None = None

    @property
    def avg_rtt(self) -> float:
        values = [r for r in self.rtts if r >= 0]
        return sum(values) / len(values) if values else -1.0

    @property
    def label(self) -> str:
        if self.timeout:
            return "* * *"
        if self.host and self.host != self.ip:
            return f"{self.host} ({self.ip})"
        return self.ip or "?"

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
