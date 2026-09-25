"""Batch check (xping check) result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._export import model_to_dict


@dataclass
class CheckOutcome:
    name: str
    type: str
    target: str
    ok: bool
    detail: str = ""
    elapsed_ms: float = 0.0
    result: Any = None  # the underlying diagnostic result (full data in JSON)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class CheckReport:
    source: str
    outcomes: list[CheckOutcome] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.ok)

    @property
    def failed(self) -> int:
        return len(self.outcomes) - self.passed

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
