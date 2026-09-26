"""DNS blocklist (xping blocklist) result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict

# listed   on the list
# policy   Spamhaus PBL only: an end-user address range (normal for home
#          connections, a problem only for a mail server)
# clean    not listed
# refused  the list refused to answer (e.g. queries via a public resolver)
# error    lookup failed or timed out
LISTED, POLICY, CLEAN, REFUSED, ERROR = "listed", "policy", "clean", "refused", "error"


@dataclass
class BlocklistCheck:
    list_name: str
    zone: str
    subject: str  # the IP or domain that was looked up
    status: str
    codes: list[str] = field(default_factory=list)  # 127.0.0.x answers
    reason: str = ""
    elapsed_ms: float | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class BlocklistResult:
    target: str
    kind: str  # "ip" | "domain"
    addresses: list[str] = field(default_factory=list)  # IPs checked (domain: its MX and A hosts)
    checks: list[BlocklistCheck] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # e.g. IPv6 addresses
    error: str | None = None

    @property
    def listed(self) -> list[str]:
        return [f"{c.list_name} ({c.subject})" for c in self.checks if c.status == LISTED]

    @property
    def listed_count(self) -> int:
        return len(self.listed)

    @property
    def answered(self) -> int:
        return sum(1 for c in self.checks if c.status in (LISTED, POLICY, CLEAN))

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
