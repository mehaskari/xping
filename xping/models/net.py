"""Local network overview result models (xping net)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class NetInterface:
    name: str
    state: str = "unknown"  # "up" | "down" | "unknown"
    mtu: int | None = None
    mac: str | None = None
    addresses: list[str] = field(default_factory=list)  # "192.168.1.5/24", "fe80::1/64"

    @property
    def loopback(self) -> bool:
        return self.name.startswith("lo") or any(
            a.startswith(("127.", "::1")) for a in self.addresses
        )

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class NetResult:
    hostname: str
    local_ipv4: str | None = None  # source address used for outbound IPv4
    local_ipv6: str | None = None
    gateway_ipv4: str | None = None
    gateway_ipv6: str | None = None
    gateway_interface: str | None = None
    dns_servers: list[str] = field(default_factory=list)
    public_ipv4: str | None = None
    public_ipv6: str | None = None
    location: str | None = None  # country code seen by Cloudflare
    colo: str | None = None  # Cloudflare data centre that answered
    interfaces: list[NetInterface] = field(default_factory=list)
    error: str | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
