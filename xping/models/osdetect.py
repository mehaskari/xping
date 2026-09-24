"""OS fingerprint (TTL heuristic) result model."""

from __future__ import annotations

from dataclasses import dataclass

from ._export import model_to_dict


@dataclass
class OsDetectResult:
    host: str
    ip: str | None = None
    ttl: int | None = None
    os_guess: str | None = None
    reasoning: str | None = None
    error: str | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
