"""IP scan result models."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class IpProbe:
    ip: str
    alive: bool
    elapsed_ms: float
    rtt_ms: float = -1.0
    error: str | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class IpScanResult:
    target: str
    probes: list[IpProbe] = field(default_factory=list)
    error: str | None = None

    @property
    def scanned(self) -> int:
        return len(self.probes)

    @property
    def alive_hosts(self) -> list[IpProbe]:
        return [probe for probe in self.probes if probe.alive]

    @property
    def alive_count(self) -> int:
        return len(self.alive_hosts)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
