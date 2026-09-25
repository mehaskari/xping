"""MTR (combined traceroute + ping) result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class MtrHop:
    ttl: int
    ip: str | None = None
    host: str | None = None
    rtts: list[float] = field(default_factory=list)
    asn: int | None = None  # origin AS of the hop address (mtr --asn)
    as_name: str | None = None

    @property
    def sent(self) -> int:
        return len(self.rtts)

    @property
    def received(self) -> int:
        return sum(1 for r in self.rtts if r >= 0)

    @property
    def loss_pct(self) -> float:
        return ((self.sent - self.received) / self.sent * 100) if self.sent else 0.0

    @property
    def last(self) -> float:
        valid = [r for r in self.rtts if r >= 0]
        return valid[-1] if valid else -1.0

    @property
    def best(self) -> float:
        valid = [r for r in self.rtts if r >= 0]
        return min(valid) if valid else -1.0

    @property
    def worst(self) -> float:
        valid = [r for r in self.rtts if r >= 0]
        return max(valid) if valid else -1.0

    @property
    def avg(self) -> float:
        valid = [r for r in self.rtts if r >= 0]
        return sum(valid) / len(valid) if valid else -1.0

    @property
    def stdev(self) -> float:
        valid = [r for r in self.rtts if r >= 0]
        if len(valid) < 2:
            return 0.0
        avg = sum(valid) / len(valid)
        return (sum((x - avg) ** 2 for x in valid) / len(valid)) ** 0.5

    @property
    def label(self) -> str:
        if self.host and self.host != self.ip:
            return f"{self.host} ({self.ip})"
        return self.ip or "???"

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class MtrResult:
    host: str
    dest_ip: str | None = None
    cycles: int = 0
    hops: list[MtrHop] = field(default_factory=list)
    error: str | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
