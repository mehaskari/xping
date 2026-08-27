"""Speed test result model."""

from dataclasses import dataclass
from ._export import model_to_dict


@dataclass
class SpeedResult:
    download_mbps: float | None = None
    upload_mbps: float | None = None
    ping_ms: float | None = None
    server: str | None = None
    error: str | None = None

    @property
    def grade(self) -> str:
        if self.download_mbps is None:
            return "Unknown"
        d = self.download_mbps
        if d >= 100: return "Excellent"
        if d >= 25:  return "Good"
        if d >= 10:  return "Fair"
        if d >= 1:   return "Poor"
        return "Critical"

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
