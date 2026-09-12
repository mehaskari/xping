"""TCP connectivity result models."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class TcpAttempt:
    seq: int
    ok: bool
    elapsed_ms: float
    error: str | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class TcpResult:
    host: str
    port: int
    ip: str
    attempts: list[TcpAttempt] = field(default_factory=list)
    resolved: bool = True
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.attempts)

    @property
    def successful(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.ok)

    @property
    def failed(self) -> int:
        return self.count - self.successful

    @property
    def success_pct(self) -> float:
        return (self.successful / self.count * 100) if self.count else 0.0

    @property
    def connect_times(self) -> list[float]:
        return [attempt.elapsed_ms for attempt in self.attempts if attempt.ok]

    @property
    def min_connect_ms(self) -> float:
        return min(self.connect_times, default=-1.0)

    @property
    def max_connect_ms(self) -> float:
        return max(self.connect_times, default=-1.0)

    @property
    def avg_connect_ms(self) -> float:
        values = self.connect_times
        return sum(values) / len(values) if values else -1.0

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
