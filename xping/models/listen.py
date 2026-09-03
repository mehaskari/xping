"""Local listening ports result model."""

from dataclasses import dataclass, field
from ._export import model_to_dict


@dataclass
class ListenEntry:
    proto: str
    local_addr: str
    local_port: int
    pid: int | None = None
    process: str | None = None

    @property
    def address(self) -> str:
        return f"{self.local_addr}:{self.local_port}"

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class ListenResult:
    entries: list[ListenEntry] = field(default_factory=list)
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.entries)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
