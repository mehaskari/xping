"""Wi-Fi link (xping wifi) result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class WifiNetwork:
    ssid: str | None = None  # None when the OS hides it (macOS without Location Services)
    bssid: str | None = None
    channel: int | None = None
    band: str | None = None  # "2.4 GHz" | "5 GHz" | "6 GHz"
    width_mhz: int | None = None
    signal_dbm: int | None = None
    noise_dbm: int | None = None
    security: str | None = None
    phy_mode: str | None = None

    @property
    def snr_db(self) -> int | None:
        if self.signal_dbm is None or self.noise_dbm is None:
            return None
        return self.signal_dbm - self.noise_dbm

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class WifiResult:
    interface: str | None = None
    connected: bool = False
    current: WifiNetwork | None = None
    tx_rate_mbps: float | None = None
    mcs: int | None = None
    country: str | None = None
    nearby: list[WifiNetwork] = field(default_factory=list)
    source: str | None = None  # the OS tool the data came from
    error: str | None = None

    @property
    def quality(self) -> str | None:
        """Signal grade, using the usual Wi-Fi design thresholds (-67 dBm is
        the common minimum for voice/video calls)."""
        s = self.current.signal_dbm if self.current else None
        if s is None:
            return None
        if s >= -55:
            return "Excellent"
        if s >= -67:
            return "Good"
        if s >= -75:
            return "Fair"
        if s >= -85:
            return "Weak"
        return "Very weak"

    @property
    def same_channel(self) -> int:
        """Nearby networks sharing (or, on 2.4 GHz, overlapping) our channel."""
        if not self.current or self.current.channel is None:
            return 0
        return sum(1 for n in self.nearby if overlaps(self.current, n))

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


def overlaps(a: WifiNetwork, b: WifiNetwork) -> bool:
    if a.channel is None or b.channel is None or a.band != b.band:
        return False
    if a.band == "2.4 GHz":
        return abs(a.channel - b.channel) <= 4  # 20 MHz channels 5 MHz apart
    return a.channel == b.channel
