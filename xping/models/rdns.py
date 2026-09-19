"""Reverse DNS (PTR) lookup result model."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class RdnsResult:
    ip: str
    hostname: str | None = None
    aliases: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def resolved(self) -> bool:
        return self.hostname is not None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
