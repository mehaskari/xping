"""Speed test result model."""

from dataclasses import dataclass

from ._export import model_to_dict

# (latency increase below this many ms, grade) — the scale common
# bufferbloat tests use; 400 ms or more is an F
BLOAT_GRADES = ((5, "A+"), (30, "A"), (60, "B"), (200, "C"), (400, "D"))


@dataclass
class SpeedResult:
    download_mbps: float | None = None
    upload_mbps: float | None = None
    ping_ms: float | None = None
    server: str | None = None
    connections: int = 1
    download_bytes: int = 0
    upload_bytes: int = 0
    error: str | None = None
    # Bufferbloat (--bufferbloat): median HTTPS round trip to the test
    # server while idle and while the link is saturated by each direction
    idle_latency_ms: float | None = None
    download_latency_ms: float | None = None
    upload_latency_ms: float | None = None

    @property
    def grade(self) -> str:
        if self.download_mbps is None:
            return "Unknown"
        d = self.download_mbps
        if d >= 100:
            return "Excellent"
        if d >= 25:
            return "Good"
        if d >= 10:
            return "Fair"
        if d >= 1:
            return "Poor"
        return "Critical"

    @property
    def bufferbloat_ms(self) -> float | None:
        """How much latency grows under load: the worse direction minus idle."""
        loaded = [v for v in (self.download_latency_ms, self.upload_latency_ms) if v is not None]
        if self.idle_latency_ms is None or not loaded:
            return None
        return max(0.0, max(loaded) - self.idle_latency_ms)

    @property
    def bufferbloat_grade(self) -> str | None:
        bloat = self.bufferbloat_ms
        if bloat is None:
            return None
        for limit, grade in BLOAT_GRADES:
            if bloat < limit:
                return grade
        return "F"

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
