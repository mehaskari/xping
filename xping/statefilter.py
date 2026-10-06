"""Debounced up/down state: one failed check is not an outage.

A target is confirmed DOWN after ``fail_after`` failed checks in a row and
UP again after ``recover_after`` passing checks in a row. Until the first
confirmation the state is unknown (None). Alerts, state changes and the
"down at the end" verdict follow the confirmed state; uptime still counts
every single check.
"""

from __future__ import annotations

from collections.abc import Iterable


class StateFilter:
    def __init__(self, fail_after: int = 1, recover_after: int = 1):
        if fail_after < 1 or recover_after < 1:
            raise ValueError("fail_after and recover_after must be at least 1")
        self.fail_after = fail_after
        self.recover_after = recover_after
        self.state: bool | None = None  # the confirmed state
        self.run = 0  # length of the current run of equal results
        self.last: bool | None = None  # the latest raw result

    def update(self, ok: bool) -> bool:
        """Feed one result; True when the confirmed state changed."""
        self.run = self.run + 1 if ok == self.last else 1
        self.last = ok
        needed = self.recover_after if ok else self.fail_after
        if ok != self.state and self.run >= needed:
            self.state = ok
            return True
        return False

    @property
    def pending(self) -> tuple[int, int] | None:
        """(results so far, results needed) while the latest results
        disagree with the confirmed state; None otherwise."""
        if self.last is None or self.last == self.state:
            return None
        return self.run, self.recover_after if self.last else self.fail_after


def outages(
    results: Iterable[tuple[float, bool]], fail_after: int = 1, recover_after: int = 1
) -> list[tuple[float, float | None]]:
    """Confirmed outages in (time, ok) results: (start, end) pairs, from the
    first failure of the run that confirmed DOWN to the first success of the
    run that confirmed UP (end None while still down)."""
    found: list[tuple[float, float | None]] = []
    state = StateFilter(fail_after, recover_after)
    run_start = 0.0
    previous: bool | None = None
    for ts, ok in results:
        if ok != previous:
            run_start = ts
        previous = ok
        if state.update(ok):
            if not ok:
                found.append((run_start, None))
            elif found and found[-1][1] is None:
                found[-1] = (found[-1][0], run_start)
    return found
