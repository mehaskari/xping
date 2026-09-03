"""DNS health check result model."""

from __future__ import annotations
from dataclasses import dataclass, field
from ._export import model_to_dict


@dataclass
class DnsCheckItem:
    name: str
    status: str   # "ok" | "warn" | "fail" | "info"
    detail: str = ""

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class DnsCheckResult:
    domain: str
    ip: str | None = None
    checks: list[DnsCheckItem] = field(default_factory=list)
    score: int = 0
    error: str | None = None

    @property
    def grade(self) -> str:
        if self.score >= 90: return "Excellent"
        if self.score >= 70: return "Good"
        if self.score >= 50: return "Fair"
        if self.score >= 25: return "Poor"
        return "Critical"

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "ok")

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
