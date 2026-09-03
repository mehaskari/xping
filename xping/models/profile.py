"""Saved target profile models."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class ProfileEntry:
    name: str
    target: str
    port: int | None = None
    note: str | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class ProfileListResult:
    profiles: list[ProfileEntry] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.profiles)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
