"""Network health score result model."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict
from .ping import PingResult


@dataclass
class HealthResult:
    host: str
    ip: str | None = None
    resolved: bool = True
    dns_resolve_ms: float | None = None
    ping: PingResult | None = None
    score: int = 0
    issues: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)  # past {ts, score, grade} runs
    error: str | None = None

    @property
    def grade(self) -> str:
        if self.score >= 90:
            return "Excellent"
        if self.score >= 75:
            return "Good"
        if self.score >= 50:
            return "Fair"
        if self.score >= 25:
            return "Poor"
        return "Critical"

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
