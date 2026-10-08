"""xping report models: saved history summarised per target."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class ReportPoint:
    ts: float
    ok: bool
    value: float | None = None  # the series' headline metric

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class ReportOutage:
    start: float  # first failed run
    end: float | None = None  # first good run after it; None while still down

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class ReportSeries:
    command: str
    target: str
    metric: str | None = None
    unit: str = ""
    points: list[ReportPoint] = field(default_factory=list)
    outages: list[ReportOutage] = field(default_factory=list)
    previous: ReportSeries | None = None  # the same length of time just before (--compare)
    better: str = "lower"  # which direction of the metric is an improvement: lower | higher

    @property
    def runs(self) -> int:
        return len(self.points)

    @property
    def up_pct(self) -> float | None:
        if not self.points:
            return None
        return sum(p.ok for p in self.points) / len(self.points) * 100

    @property
    def last_ok(self) -> bool | None:
        return self.points[-1].ok if self.points else None

    @property
    def latest(self) -> float | None:
        return self.points[-1].value if self.points else None

    @property
    def values(self) -> list[float]:
        return [p.value for p in self.points if p.value is not None]

    @property
    def median(self) -> float | None:
        values = sorted(self.values)
        if not values:
            return None
        middle = len(values) // 2
        return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2

    def percentile(self, pct: float) -> float | None:
        """Nearest-rank percentile of the values (p95 = percentile(95))."""
        values = sorted(self.values)
        if not values:
            return None
        rank = max(1, -(-len(values) * pct // 100))  # ceil without math
        return values[int(rank) - 1]

    @property
    def p95(self) -> float | None:
        return self.percentile(95)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class ReportResult:
    generated: float
    path: str | None = None  # where the HTML was written
    since: float | None = None  # only runs newer than this (unix time)
    compared: bool = False  # each series carries the period before as .previous
    series: list[ReportSeries] = field(default_factory=list)
    error: str | None = None

    @property
    def runs(self) -> int:
        return sum(s.runs for s in self.series)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
