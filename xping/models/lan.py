"""Local network device discovery (xping lan) result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class LanDevice:
    ip: str
    mac: str | None = None
    vendor: str | None = None  # from the MAC prefix, when a vendor database is installed
    name: str | None = None  # mDNS or the router's DNS
    random_mac: bool = False  # a locally administered (private, randomised) address
    is_self: bool = False
    is_gateway: bool = False

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class LanResult:
    network: str | None = None  # "192.168.1.0/24"
    interface: str | None = None
    gateway: str | None = None
    scanned: int = 0  # addresses probed (0 with --no-scan)
    devices: list[LanDevice] = field(default_factory=list)
    vendor_db: str | None = None  # which vendor database was used, if any
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.devices)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
