"""TLS/SSL certificate inspection result model."""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class TlsResult:
    host: str
    port: int
    ip: str | None = None
    protocol: str | None = None
    cipher: str | None = None
    subject: str | None = None
    issuer: str | None = None
    not_before: str | None = None
    not_after: str | None = None
    san: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def days_remaining(self) -> int | None:
        if not self.not_after:
            return None
        try:
            expiry_ts = ssl.cert_time_to_seconds(self.not_after)
        except (ValueError, OverflowError):
            return None
        return int((expiry_ts - time.time()) / 86400)

    @property
    def expired(self) -> bool:
        days = self.days_remaining
        return days is not None and days < 0

    @property
    def expiring_soon(self) -> bool:
        days = self.days_remaining
        return days is not None and 0 <= days <= 14

    @property
    def valid(self) -> bool:
        return self.error is None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
