"""DNS lookup result model."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class DnsResult:
    host: str
    ipv4: list[str] = field(default_factory=list)
    ipv6: list[str] = field(default_factory=list)
    cname: str | None = None
    mx: list[tuple[int, str]] = field(default_factory=list)
    ns: list[str] = field(default_factory=list)
    txt: list[str] = field(default_factory=list)
    ttl: int | None = None
    reverse: dict[str, str] = field(default_factory=dict)
    raw_dig: str | None = None
    # record type -> DNS status for queries that failed (SERVFAIL, TIMEOUT, …),
    # as opposed to records that are genuinely absent
    query_errors: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
