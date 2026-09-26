"""SMTP server (xping smtp) result models."""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class SmtpResult:
    host: str  # what the user asked for
    server: str | None = None  # the host actually tested (an MX when host is a mail domain)
    port: int = 25
    ip: str | None = None
    mx_hosts: list[str] = field(default_factory=list)  # "10 mx1.example.com", …
    reverse_dns: str | None = None  # PTR of the server IP
    forward_confirmed: bool | None = None  # the PTR name resolves back to the IP
    connect_ms: float | None = None
    banner: str | None = None
    banner_code: int | None = None
    extensions: list[str] = field(default_factory=list)  # EHLO keywords (after TLS if used)
    starttls_offered: bool | None = None
    implicit_tls: bool = False  # port 465 (SMTPS)
    tls_version: str | None = None
    tls_cipher: str | None = None
    tls_ms: float | None = None
    cert_subject: str | None = None
    cert_issuer: str | None = None
    cert_not_after: str | None = None
    cert_error: str | None = None  # verification failure (hostname, expiry, self-signed …)
    auth: list[str] = field(default_factory=list)  # AUTH mechanisms offered
    max_size: int | None = None  # SIZE limit in bytes
    error: str | None = None

    @property
    def tls(self) -> bool:
        return self.tls_version is not None

    @property
    def cert_days(self) -> int | None:
        if not self.cert_not_after:
            return None
        try:
            expires = ssl.cert_time_to_seconds(self.cert_not_after)
        except ValueError:
            return None
        return int((expires - time.time()) // 86400)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
