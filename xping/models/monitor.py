"""xping monitor result models: many checks followed over time."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class MonitorSample:
    ts: float  # unix time the check finished
    ok: bool
    value: float | None = None  # the check's headline metric (see MonitoredCheck.metric)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class MonitoredCheck:
    name: str
    type: str
    target: str
    every: float  # seconds between runs
    metric: str | None = None  # e.g. "Average RTT"; None when the type has no number to follow
    unit: str = ""
    detail: str = ""  # the latest verdict or one-line summary
    since: float | None = None  # when the current up/down state began
    samples: list[MonitorSample] = field(default_factory=list)

    @property
    def checks(self) -> int:
        return len(self.samples)

    @property
    def last_ok(self) -> bool | None:
        return self.samples[-1].ok if self.samples else None

    @property
    def latest(self) -> float | None:
        return self.samples[-1].value if self.samples else None

    @property
    def up_pct(self) -> float | None:
        if not self.samples:
            return None
        return sum(s.ok for s in self.samples) / len(self.samples) * 100

    @property
    def outages(self) -> int:
        """Times the check went down (including starting down)."""
        count, previous = 0, True
        for sample in self.samples:
            if previous and not sample.ok:
                count += 1
            previous = sample.ok
        return count

    @property
    def longest_outage_s(self) -> float:
        """Longest run of failures, from the first failure to the next
        success (or the last check)."""
        longest, start = 0.0, None
        for sample in self.samples:
            if not sample.ok and start is None:
                start = sample.ts
            elif sample.ok and start is not None:
                longest = max(longest, sample.ts - start)
                start = None
        if start is not None:
            longest = max(longest, self.samples[-1].ts - start)
        return longest

    @property
    def average(self) -> float | None:
        values = [s.value for s in self.samples if s.value is not None]
        return sum(values) / len(values) if values else None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class MonitorResult:
    source: str
    started: float
    ended: float | None = None
    checks: list[MonitoredCheck] = field(default_factory=list)

    @property
    def down(self) -> list[str]:
        """Checks that failed their latest run."""
        return [c.name for c in self.checks if c.last_ok is False]

    @property
    def ok(self) -> bool:
        return not self.down

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
