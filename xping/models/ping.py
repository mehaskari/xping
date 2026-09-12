"""Ping diagnostic result model."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class PingResult:
    host: str
    ip: str
    count: int
    rtts: list[float] = field(default_factory=list)
    resolved: bool = True

    @property
    def sent(self):
        return self.count

    @property
    def received(self):
        return sum(1 for r in self.rtts if r >= 0)

    @property
    def lost(self):
        return self.sent - self.received

    @property
    def loss_pct(self):
        return (self.lost / self.sent * 100) if self.sent else 100

    @property
    def min_rtt(self):
        return min((r for r in self.rtts if r >= 0), default=-1)

    @property
    def max_rtt(self):
        return max((r for r in self.rtts if r >= 0), default=-1)

    @property
    def avg_rtt(self):
        values = [r for r in self.rtts if r >= 0]
        return sum(values) / len(values) if values else -1

    @property
    def jitter(self):
        values = [r for r in self.rtts if r >= 0]
        if len(values) < 2:
            return 0.0
        return sum(abs(values[i + 1] - values[i]) for i in range(len(values) - 1)) / (len(values) - 1)

    @property
    def std_dev(self):
        values = [r for r in self.rtts if r >= 0]
        if len(values) < 2:
            return 0.0
        avg = sum(values) / len(values)
        return (sum((x - avg) ** 2 for x in values) / len(values)) ** 0.5

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
