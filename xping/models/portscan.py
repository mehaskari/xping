"""Port scan result models."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class PortResult:
    port: int
    open: bool
    elapsed_ms: float
    service: str | None = None
    banner: str | None = None
    error: str | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class PortScanResult:
    host: str
    ip: str
    ports: list[int]
    results: list[PortResult] = field(default_factory=list)
    resolved: bool = True
    error: str | None = None

    @property
    def scanned(self) -> int:
        return len(self.results)

    @property
    def open_ports(self) -> list[PortResult]:
        return [result for result in self.results if result.open]

    @property
    def closed_ports(self) -> int:
        return self.scanned - len(self.open_ports)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
