"""Watch-mode (repeated check) result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class WatchSample:
    seq: int
    ts: float  # unix time of the check
    ok: bool
    latency_ms: float | None = None
    detail: str = ""

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class WatchResult:
    target: str
    check: str  # "tcp" | "http" | "health"
    until_up: bool = False
    samples: list[WatchSample] = field(default_factory=list)

    @property
    def checks(self) -> int:
        return len(self.samples)

    @property
    def up_pct(self) -> float:
        return sum(s.ok for s in self.samples) / len(self.samples) * 100 if self.samples else 0.0

    @property
    def last_ok(self) -> bool:
        return bool(self.samples) and self.samples[-1].ok

    @property
    def transitions(self) -> int:
        return sum(1 for a, b in zip(self.samples, self.samples[1:], strict=False) if a.ok != b.ok)

    @property
    def longest_outage_s(self) -> float:
        """Longest run of failed checks, measured from its first failure to
        the next success (or the last check)."""
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

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
