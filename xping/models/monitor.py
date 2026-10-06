"""xping monitor result models: many checks followed over time."""

from __future__ import annotations

from dataclasses import dataclass, field

from xping.statefilter import outages as confirmed_outages

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
    fail_after: int = 1  # failed runs in a row before the check counts as DOWN
    recover_after: int = 1  # passing runs in a row before it counts as UP again
    up: bool | None = None  # the confirmed state (None until first confirmed)
    since: float | None = None  # when the confirmed state began
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

    def _outages(self) -> list[tuple[float, float | None]]:
        return confirmed_outages(
            [(s.ts, s.ok) for s in self.samples],
            self.fail_after,
            self.recover_after,
        )

    @property
    def outages(self) -> int:
        """Confirmed outages (fail_after failures in a row each)."""
        return len(self._outages())

    @property
    def longest_outage_s(self) -> float:
        """Longest confirmed outage, from its first failed run to the first
        good run of the recovery (or the last run while still down)."""
        end_of_data = self.samples[-1].ts if self.samples else 0.0
        return max(
            ((end if end is not None else end_of_data) - start for start, end in self._outages()),
            default=0.0,
        )

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
        """Checks whose confirmed state is DOWN."""
        return [c.name for c in self.checks if c.up is False]

    @property
    def ok(self) -> bool:
        return not self.down

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
