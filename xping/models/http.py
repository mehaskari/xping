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
class HttpResult:
    url: str
    final_url: str | None = None
    status_code: int | None = None
    reason: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    redirects: list[RedirectHop] = field(default_factory=list)
    ttfb_ms: float | None = None
    total_ms: float | None = None
    body_bytes: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 400

    @property
    def redirect_count(self) -> int:
        return len(self.redirects)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
