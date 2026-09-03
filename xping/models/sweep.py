"""IP sweep result models."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class HostProbe:
    ip: str
    open_ports: list[int] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def alive(self) -> bool:
        return bool(self.open_ports)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class SweepResult:
    target: str
    ports: list[int]
    hosts: list[HostProbe] = field(default_factory=list)
    error: str | None = None

    @property
    def scanned(self) -> int:
        return len(self.hosts)

    @property
    def alive_hosts(self) -> list[HostProbe]:
        return [host for host in self.hosts if host.alive]

    @property
    def alive_count(self) -> int:
        return len(self.alive_hosts)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
