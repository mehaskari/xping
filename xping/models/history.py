"""Saved-results history (xping history) models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class HistoryEntry:
    command: str
    target: str
    runs: int
    first: float  # unix time of the oldest kept run
    last: float

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class HistoryRun:
    ts: float
    ok: bool
    values: dict[str, float | None] = field(default_factory=dict)  # metric label -> value

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class HistoryResult:
    command: str | None = None  # None: the list of everything recorded
    target: str | None = None
    entries: list[HistoryEntry] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    units: dict[str, str] = field(default_factory=dict)
    runs: list[HistoryRun] = field(default_factory=list)
    median: float | None = None  # of the headline metric over the earlier runs
    latest_vs_median_pct: float | None = None
    cleared: int | None = None  # files removed by --clear
    error: str | None = None

    @property
    def ok_pct(self) -> float | None:
        return sum(r.ok for r in self.runs) / len(self.runs) * 100 if self.runs else None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
