"""Connectivity doctor (xping doctor) result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._export import model_to_dict

# Step status values, in order of severity
OK, INFO, SKIP, WARN, FAIL = "ok", "info", "skip", "warn", "fail"


@dataclass
class DoctorStep:
    key: str  # stable id: interface, gateway, internet, dns, quality, captive, https, ipv6, target
    name: str  # human label
    status: str  # ok | info | skip | warn | fail
    detail: str = ""
    hint: str = ""  # what to do about a warn/fail
    elapsed_ms: float | None = None

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class DoctorResult:
    target: str | None = None
    port: int | None = None
    steps: list[DoctorStep] = field(default_factory=list)
    diagnosis: str = ""
    hint: str = ""

    def step(self, key: str) -> DoctorStep | None:
        return next((s for s in self.steps if s.key == key), None)

    @property
    def ok(self) -> bool:
        return not any(s.status == FAIL for s in self.steps)

    @property
    def failed(self) -> list[str]:
        return [s.key for s in self.steps if s.status == FAIL]

    @property
    def warnings(self) -> list[str]:
        return [s.key for s in self.steps if s.status == WARN]

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
