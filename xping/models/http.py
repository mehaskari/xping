"""HTTP diagnostic result models."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class RedirectHop:
    url: str
    status_code: int

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class SecurityHeader:
    name: str
    status: str  # "ok" | "warn" | "missing"
    value: str | None = None
    note: str = ""

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class HttpResult:
    url: str
    final_url: str | None = None
    ip: str | None = None  # address the final request connected to
    status_code: int | None = None
    reason: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    redirects: list[RedirectHop] = field(default_factory=list)
    ttfb_ms: float | None = None  # request sent → response headers (server time)
    total_ms: float | None = None  # wall time, including every redirect
    body_bytes: int = 0
    dns_ms: float | None = None  # final request's phases ↓
    tcp_ms: float | None = None  # TCP connect only (TLS is tls_ms)
    tls_ms: float | None = None
    transfer_ms: float | None = None  # body download after the headers
    redirect_ms: float | None = None  # time spent following redirects
    http_version: str | None = None
    tls_version: str | None = None
    tls_cipher: str | None = None
    security: list[SecurityHeader] = field(default_factory=list)
    h2_supported: bool | None = None  # None = ALPN probe failed / not HTTPS
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 400

    @property
    def redirect_count(self) -> int:
        return len(self.redirects)

    @property
    def security_missing(self) -> list[str]:
        return [h.name for h in self.security if h.status != "ok"]

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
