"""NTP clock-offset result models (xping ntp)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class NtpSample:
    seq: int
    offset_ms: float | None = None  # server clock minus local clock
    delay_ms: float | None = None  # network round trip
    error: str | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class NtpResult:
    server: str
    ip: str | None = None
    stratum: int | None = None  # 1 = primary reference, 16 = unsynchronised
    reference: str | None = None  # reference ID (e.g. "GPS" or an upstream IP)
    leap: int | None = None  # 3 = clock not synchronised
    version: int | None = None
    samples: list[NtpSample] = field(default_factory=list)
    error: str | None = None

    @property
    def answered(self) -> list[NtpSample]:
        return [s for s in self.samples if s.offset_ms is not None]

    @property
    def best(self) -> NtpSample | None:
        """The sample with the lowest delay — its offset is the most accurate."""
        return min(self.answered, key=lambda s: s.delay_ms or 0.0, default=None)

    @property
    def offset_ms(self) -> float | None:
        best = self.best
        return best.offset_ms if best else None

    @property
    def delay_ms(self) -> float | None:
        best = self.best
        return best.delay_ms if best else None

    @property
    def synchronized(self) -> bool:
        return self.leap != 3 and self.stratum is not None and 1 <= self.stratum <= 15

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
