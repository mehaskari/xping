"""DNS propagation check result models (xping propagation)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ._export import model_to_dict

_ANSWERED = ("NOERROR", "NXDOMAIN")


@dataclass
class ResolverAnswer:
    resolver: str
    server: str | None  # None = the system resolver
    status: str  # NOERROR, NXDOMAIN, SERVFAIL, TIMEOUT, …
    records: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def answered(self) -> bool:
        return self.status in _ANSWERED

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)


@dataclass
class PropagationResult:
    name: str
    rtype: str
    expected: list[str] = field(default_factory=list)
    answers: list[ResolverAnswer] = field(default_factory=list)
    error: str | None = None

    @property
    def answered(self) -> list[ResolverAnswer]:
        return [a for a in self.answers if a.answered]

    @property
    def distinct_answers(self) -> int:
        return len({tuple(a.records) for a in self.answered})

    @property
    def consistent(self) -> bool:
        """True when every resolver that answered returned the same records."""
        return self.distinct_answers <= 1

    @property
    def majority(self) -> list[str]:
        counts = Counter(tuple(a.records) for a in self.answered)
        return list(counts.most_common(1)[0][0]) if counts else []

    def matches(self, answer: ResolverAnswer) -> bool | None:
        """Whether *answer* contains every --expect value (None without --expect)."""
        if not self.expected:
            return None
        return answer.answered and all(e in answer.records for e in self.expected)

    @property
    def matching(self) -> int:
        return sum(1 for a in self.answered if self.matches(a))

    def problems(self) -> list[tuple[str, bool]]:
        """(message, caused_by_threshold) for the exit-code verdict. Different
        answers alone are not a failure — CDNs and geo-DNS legitimately vary."""
        if self.error:
            return [(self.error, False)]
        if not self.answered:
            return [(f"no resolver answered for {self.name} {self.rtype}", False)]
        if self.expected and self.matching < len(self.answered):
            missing = len(self.answered) - self.matching
            want = ", ".join(self.expected)
            return [(f"{missing} of {len(self.answered)} resolvers do not return {want}", True)]
        return []

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
