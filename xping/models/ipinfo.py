"""IP address information (xping ip) result model."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class IpInfoResult:
    query: str  # what was asked: an address, a host name, or "" for your own
    ip: str | None = None
    version: int | None = None
    scope: str | None = None  # public, private, CGNAT, loopback, link-local, …
    ptr: str | None = None  # reverse DNS name
    fcrdns: bool | None = None  # does the PTR name resolve back to the address?
    asn: int | None = None
    as_name: str | None = None
    prefix: str | None = None
    country: str | None = None
    blocklist_listed: list[str] = field(default_factory=list)
    blocklist_policy: list[str] = field(default_factory=list)
    blocklist_checked: int = 0  # lists that answered
    blocklist_error: str | None = None
    error: str | None = None

    @property
    def public(self) -> bool:
        return self.scope == "public"

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
