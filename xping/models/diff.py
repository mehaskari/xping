"""Run comparison (xping diff) result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class MetricChange:
    label: str
    before: float | None
    after: float | None
    unit: str = ""
    better: str = "lower"  # which direction is an improvement: lower | higher | neutral
    change_pct: float | None = None
    verdict: str = "same"  # better | worse | same | changed

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class DiffResult:
    kind: str  # ping, trace, http, … or generic
    before: str = ""
    after: str = ""
    metrics: list[MetricChange] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)  # status / set / route changes, as text
    regressions: list[str] = field(default_factory=list)
    max_regression: float | None = None
    error: str | None = None

    @property
    def worse(self) -> int:
        return sum(1 for m in self.metrics if m.verdict == "worse")

    @property
    def better(self) -> int:
        return sum(1 for m in self.metrics if m.verdict == "better")

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
