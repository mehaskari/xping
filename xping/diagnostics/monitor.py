"""
xping.diagnostics.monitor — follow every check of a check file over time.

The checks of an ``xping check`` file run again and again, each on its
own schedule (``every`` in the file, or ``--every``). In a terminal the
state is a table redrawn in place: up or down, the latest value of the
check's headline metric, a trend, uptime and how long the current state
has lasted. Elsewhere (cron, systemd, a pipe) one line is printed per
state change. Ctrl-C ends the run with a summary; the exit code says
whether every check was up at the end.

Alerts (``--notify`` / ``--webhook``) fire on every down/up change and
``--save`` keeps each result in the history, exactly like the single
commands do.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from types import SimpleNamespace

from xping.diagnostics import history
from xping.diagnostics.check import ConfigError, display_target, load_config, run_entries
from xping.diagnostics.notify import Notifier
from xping.models.check import CheckOutcome
from xping.models.monitor import MonitoredCheck, MonitorResult, MonitorSample
from xping.render.errors import warn
from xping.render.views import monitor as monitor_view

# Field defaults the single commands use, so a monitored check is saved
# under the same history target as e.g. `xping tls example.com --save`.
_TARGET_FIELDS = ("host", "port", "url", "domain", "target", "server", "interface")
_DEFAULT_PORTS = {"tls": 443, "smtp": 25}


def history_target(entry: dict) -> str | None:
    """The history target of *entry*, or None when its type has no history."""
    kind = entry["type"]
    if kind not in history.TARGETS:
        return None
    fields = {name: entry.get(name) for name in _TARGET_FIELDS}
    if fields["port"] is None:
        fields["port"] = _DEFAULT_PORTS.get(kind)
    if kind == "doctor":
        target = entry.get("target")
        fields["host"] = None if target in (None, "internet") else target
    if kind == "wifi" and fields["interface"] == "default":
        fields["interface"] = None
    return history.TARGETS[kind](SimpleNamespace(**fields))


def _every(entry: dict, default: float, index: int) -> float:
    value = entry.get("every", default)
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        raise ConfigError(f"check #{index}: 'every' must be a positive number of seconds")
    return seconds


class _Tracker:
    """Applies outcomes to one MonitoredCheck: state, alerts and saving."""

    def __init__(self, entry: dict, check: MonitoredCheck, notifier, save: bool):
        self.entry = entry
        self.check = check
        self.notifier = notifier
        self.save = save
        self.target = history_target(entry) if save else None

    def apply(self, outcome: CheckOutcome, ts: float, report: Callable | None) -> None:
        check = self.check
        value = None
        if outcome.result is not None and check.metric:
            _metric, value = history.headline(check.type, outcome.result)
        previous = check.last_ok
        check.samples.append(MonitorSample(ts=ts, ok=outcome.ok, value=value))
        check.detail = outcome.detail
        if previous is None or previous != outcome.ok:
            check.since = ts
            if report is not None:
                report(check, ts, previous)
        if self.notifier is not None:
            latency = value if check.unit == "ms" else None
            self.notifier.observe(outcome.ok, previous, outcome.detail, latency)
        if self.target is not None and outcome.result is not None:
            try:
                history.record(check.type, self.target, outcome.result, outcome.ok)
            except OSError as exc:
                warn(f"could not save {check.name} to history: {exc}")
                self.target = None  # warn once per check


def monitor(
    path: str,
    every: float = 30.0,
    workers: int = 8,
    rounds: int | None = None,
    save: bool = False,
    notify: bool = False,
    webhook: str | None = None,
    quiet: bool = False,
    live: bool | None = None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    run: Callable[[list[dict], int], list[CheckOutcome]] = run_entries,
) -> MonitorResult:
    """Run the checks in *path* until Ctrl-C (or *rounds* runs of each)."""
    entries = load_config(path)
    result = MonitorResult(source=path, started=clock())
    trackers = []
    for index, entry in enumerate(entries, 1):
        metrics = history.followed_metrics(entry["type"])
        check = MonitoredCheck(
            name=str(entry["name"]),
            type=entry["type"],
            target=display_target(entry),
            every=_every(entry, every, index),
            metric=metrics[0].label if metrics else None,
            unit=metrics[0].unit if metrics else "",
        )
        result.checks.append(check)
        notifier = Notifier(check.name, check.type, notify, webhook) if notify or webhook else None
        trackers.append(_Tracker(entry, check, notifier, save))

    if live is None:
        live = sys.stdout.isatty()
    live = live and not quiet
    report = None if quiet or live else monitor_view.print_change
    if not quiet:
        monitor_view.print_header(result)

    due = [result.started] * len(entries)
    printed = 0

    def pending(i: int) -> bool:
        return rounds is None or trackers[i].check.checks < rounds

    try:
        while any(pending(i) for i in range(len(entries))):
            now = clock()
            ready = [i for i in range(len(entries)) if pending(i) and due[i] <= now]
            if ready:
                outcomes = run([entries[i] for i in ready], workers)
                finished = clock()
                for i, outcome in zip(ready, outcomes, strict=True):
                    trackers[i].apply(outcome, finished, report)
                    # the next run is due one interval after this one was;
                    # after a slow run, start from now instead of catching up
                    due[i] = max(due[i] + trackers[i].check.every, finished)
            if live:
                printed = monitor_view.redraw(result, clock(), printed)
            waiting = [due[i] for i in range(len(entries)) if pending(i)]
            if not waiting:
                break
            pause = min(waiting) - clock()
            if live:
                pause = min(pause, 1.0)  # keep the "for" column ticking
            if pause > 0:
                sleep(pause)
    except KeyboardInterrupt:
        if not quiet:
            print()
    finally:
        for tracker in trackers:
            if tracker.notifier is not None:
                tracker.notifier.flush()

    result.ended = clock()
    if not quiet:
        monitor_view.print_summary(result)
    return result
