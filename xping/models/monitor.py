"""xping monitor result models: many checks followed over time."""

from __future__ import annotations

from dataclasses import dataclass, field

from xping.statefilter import StateFilter

from ._export import model_to_dict


@dataclass
class MonitorSample:
    ts: float  # unix time the check finished
    ok: bool
    value: float | None = None  # the check's headline metric (see MonitoredCheck.metric)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


# Runs kept per check for the trend column and exports. Totals (runs,
# failures, uptime, average, outages) count every run since the start, so a
# monitor that runs for months does not grow in memory.
KEEP_SAMPLES = 1000


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
    samples: list[MonitorSample] = field(default_factory=list)  # the latest KEEP_SAMPLES runs

    def __post_init__(self) -> None:
        # running totals: plain attributes, not fields, so exports show the
        # computed properties below instead
        self._runs = 0
        self._failures = 0
        self._value_total = 0.0
        self._value_count = 0
        self._spans: list[tuple[float, float | None]] = []  # confirmed outages
        self._filter = StateFilter(self.fail_after, self.recover_after)
        self._streak_start = 0.0
        self._previous: bool | None = None
        initial, self.samples = self.samples, []
        for sample in initial:
            self.record(sample)

    def set_debounce(self, fail_after: int, recover_after: int) -> None:
        """New fail_after / recover_after from here on."""
        self.fail_after = self._filter.fail_after = fail_after
        self.recover_after = self._filter.recover_after = recover_after

    def record(self, sample: MonitorSample) -> None:
        """Add one run: totals, outages and the recent samples."""
        self._runs += 1
        self._failures += not sample.ok
        if sample.value is not None:
            self._value_total += sample.value
            self._value_count += 1
        # outages exactly like statefilter.outages(): from the first failure
        # of the streak that confirmed DOWN to the first success of the
        # streak that confirmed UP
        if sample.ok != self._previous:
            self._streak_start = sample.ts
        self._previous = sample.ok
        if self._filter.update(sample.ok):
            if not sample.ok:
                self._spans.append((self._streak_start, None))
            elif self._spans and self._spans[-1][1] is None:
                self._spans[-1] = (self._spans[-1][0], self._streak_start)
        self.samples.append(sample)
        keep = max(KEEP_SAMPLES, self.fail_after, self.recover_after)
        if len(self.samples) > keep:
            del self.samples[: len(self.samples) - keep]

    @property
    def checks(self) -> int:
        return self._runs

    @property
    def failures(self) -> int:
        return self._failures

    @property
    def last_ok(self) -> bool | None:
        return self.samples[-1].ok if self.samples else None

    @property
    def latest(self) -> float | None:
        return self.samples[-1].value if self.samples else None

    @property
    def up_pct(self) -> float | None:
        if not self._runs:
            return None
        return (self._runs - self._failures) / self._runs * 100

    @property
    def outages(self) -> int:
        """Confirmed outages (fail_after failures in a row each)."""
        return len(self._spans)

    @property
    def outage_spans(self) -> list[tuple[float, float | None]]:
        """Each confirmed outage: (start, end), end None while still down."""
        return list(self._spans)

    @property
    def longest_outage_s(self) -> float:
        """Longest confirmed outage, from its first failed run to the first
        good run of the recovery (or the last run while still down)."""
        end_of_data = self.samples[-1].ts if self.samples else 0.0
        return max(
            ((end if end is not None else end_of_data) - start for start, end in self._spans),
            default=0.0,
        )

    @property
    def average(self) -> float | None:
        return self._value_total / self._value_count if self._value_count else None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class MonitorResult:
    source: str
    started: float
    ended: float | None = None
    checks: list[MonitoredCheck] = field(default_factory=list)
    metrics_url: str | None = None  # where --metrics served them
    status_url: str | None = None  # where --status-page served them

    @property
    def down(self) -> list[str]:
        """Checks whose confirmed state is DOWN."""
        return [c.name for c in self.checks if c.up is False]

    @property
    def ok(self) -> bool:
        return not self.down

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
