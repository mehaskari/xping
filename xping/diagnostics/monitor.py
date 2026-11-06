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
commands do. ``--metrics`` serves the checks to Prometheus at /metrics
(see xping.exporters.prometheus), ``--status-page`` as a live web page (see
xping.exporters.status_page).

With ``--resume`` the checks go on from where the last monitor of the same
source stopped (see xping.diagnostics.monitor_state).

A check file is followed while monitor runs: when it changes, new checks
start, removed ones stop and the others keep their numbers. A file that does
not load is reported and the running checks carry on.
"""

from __future__ import annotations

import functools
import os
import sys
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace

from xping.diagnostics import history, monitor_state
from xping.diagnostics.check import ConfigError, display_target, load_config, run_entries
from xping.diagnostics.notify import Notifier
from xping.models.check import CheckOutcome
from xping.models.monitor import MonitoredCheck, MonitorResult, MonitorSample
from xping.render.errors import warn
from xping.render.progress import clear_lines, line_buffered
from xping.render.views import monitor as monitor_view
from xping.statefilter import StateFilter

# Field defaults the single commands use, so a monitored check is saved
# under the same history target as e.g. `xping tls example.com --save`.
_TARGET_FIELDS = ("host", "port", "url", "domain", "target", "server", "interface")
_DEFAULT_PORTS = {"tls": 443, "smtp": 25}
RELOAD_CHECK = 2.0  # longest time a change of the check file goes unnoticed
SAVE_EVERY = 60.0  # seconds between saves of the state (--resume)


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


def _count(entry: dict, key: str, default: int, index: int) -> int:
    value = entry.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"check #{index}: '{key}' must be a whole number of at least 1")
    return value


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
        self.state = StateFilter(check.fail_after, check.recover_after)
        self.due = 0.0  # when the next run starts
        self.runs = 0  # runs by this monitor (the rounds of --rounds)

    @property
    def key(self) -> tuple[str, str, str]:
        """What makes a check the same one after the file changed."""
        return self.check.name, self.check.type, self.check.target

    def resume(self, state: dict) -> bool:
        """Go on from a saved state; False when it is unusable."""
        check = self.check
        try:
            check.restore_state(state)
        except (KeyError, TypeError, ValueError):
            return False
        self.state.state = check.up
        if self.notifier is not None and check.up is False:
            self.notifier.down_since = check.since  # "up again after" the whole outage
        return True

    def adopt(self, other: _Tracker, now: float) -> None:
        """Take the settings of the same check from a reloaded file."""
        self.entry = other.entry
        self.check.every = other.check.every
        self.due = min(self.due, now + other.check.every)
        self.check.set_debounce(other.check.fail_after, other.check.recover_after)
        self.state.fail_after = other.check.fail_after
        self.state.recover_after = other.check.recover_after

    def apply(self, outcome: CheckOutcome, ts: float, report: Callable | None) -> None:
        check = self.check
        self.runs += 1
        value = None
        if outcome.result is not None and check.metric:
            _metric, value = history.headline(check.type, outcome.result)
        check.record(MonitorSample(ts=ts, ok=outcome.ok, value=value))
        check.detail = outcome.detail
        previous, previous_since = check.up, check.since
        if self.state.update(outcome.ok):
            # the outage (or recovery) began with the first run of this streak
            changed_at = check.samples[-self.state.run].ts
            check.up, check.since = self.state.state, changed_at
            if report is not None:
                report(check, ts, previous, previous_since)
            if self.notifier is not None:
                latency = value if check.unit == "ms" else None
                self.notifier.observe(
                    bool(check.up), previous, outcome.detail, latency, since=changed_at
                )
        if self.notifier is not None:
            self.notifier.still_down(outcome.detail)
        if self.target is not None and outcome.result is not None:
            try:
                history.record(check.type, self.target, outcome.result, outcome.ok)
            except OSError as exc:
                warn(f"could not save {check.name} to history: {exc}")
                self.target = None  # warn once per check


class _FileWatch:
    """Notices that a file changed; a missing file is not a change."""

    def __init__(self, path: str):
        self.path = path
        self.stamp = self._stamp()

    def _stamp(self) -> tuple[int, int] | None:
        try:
            stat = os.stat(self.path)
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def changed(self) -> bool:
        stamp = self._stamp()
        if stamp is None or stamp == self.stamp:
            return False
        self.stamp = stamp
        return True


def _merge(
    trackers: list[_Tracker], fresh: list[_Tracker], now: float
) -> tuple[list[_Tracker], list[str], list[_Tracker]]:
    """The checks of a reloaded file, in its order: the ones already running
    go on, the new ones start now. Returns them, the names of the new ones
    and the trackers of the removed ones."""
    running = {tracker.key: tracker for tracker in trackers}
    merged, added = [], []
    for tracker in fresh:
        known = running.pop(tracker.key, None)
        if known is None:
            tracker.due = now
            added.append(tracker.check.name)
            merged.append(tracker)
        else:
            known.adopt(tracker, now)
            merged.append(known)
    return merged, added, list(running.values())


def _serve(
    result: MonitorResult,
    lock: threading.Lock,
    metrics: tuple[str, int] | None,
    status_page: tuple[str, int] | None,
    clock: Callable[[], float],
) -> list:
    """Start the HTTP servers: one per address, so --metrics and
    --status-page can share a port or use two."""
    if metrics is None and status_page is None:
        return []
    from xping.exporters import prometheus
    from xping.exporters import status_page as page

    def locked(render: Callable[..., str], *args) -> Callable[[], str]:
        def produce() -> str:
            with lock:
                return render(result, *(arg() for arg in args))

        return produce

    pages = {
        "/": (page.HTML_TYPE, locked(page.render, clock)),
        "/status.json": (page.JSON_TYPE, locked(page.to_json, clock)),
    }
    servers: list = []
    try:
        for address in dict.fromkeys(a for a in (metrics, status_page) if a is not None):
            extra = pages if address == status_page else None
            server = prometheus.MetricsServer(*address, locked(prometheus.render), extra)
            servers.append(server.start())
            url = f"http://{prometheus.format_listen(*server.address)}"
            if address == metrics:
                result.metrics_url = f"{url}/metrics"
            if address == status_page:
                result.status_url = f"{url}/"
    except prometheus.ListenError:
        for server in servers:
            server.stop()
        raise
    return servers


def monitor(
    path: str | None,
    every: float = 30.0,
    workers: int = 8,
    rounds: int | None = None,
    save: bool = False,
    notify: bool = False,
    webhook: str | None = None,
    fail_after: int = 1,
    recover_after: int = 1,
    quiet: bool = False,
    live: bool | None = None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    run: Callable[[list[dict], int], list[CheckOutcome]] = run_entries,
    entries: list[dict] | None = None,
    metrics: tuple[str, int] | None = None,
    status_page: tuple[str, int] | None = None,
    remind: float | None = None,
    resume: bool = False,
) -> MonitorResult:
    """Run the checks in *path* (or the ready-made *entries*, e.g. built from
    command-line targets) until Ctrl-C, or *rounds* runs of each. With
    *metrics* (host, port), Prometheus can scrape the checks meanwhile; with
    *status_page* (host, port), a browser can follow them."""
    if entries is None:
        if path is None:
            raise ConfigError("no checks to monitor")
        entries = load_config(path)
    source = path or ", ".join(str(e["name"]) for e in entries)
    result = MonitorResult(source=source, started=clock())

    def track(entry: dict, index: int) -> _Tracker:
        followed = history.followed_metrics(entry["type"])
        check = MonitoredCheck(
            name=str(entry["name"]),
            type=entry["type"],
            target=display_target(entry),
            every=_every(entry, every, index),
            fail_after=_count(entry, "fail_after", fail_after, index),
            recover_after=_count(entry, "recover_after", recover_after, index),
            metric=followed[0].label if followed else None,
            unit=followed[0].unit if followed else "",
        )
        notifier = (
            Notifier(check.name, check.type, notify, webhook, clock=clock, remind=remind)
            if notify or webhook
            else None
        )
        return _Tracker(entry, check, notifier, save)

    trackers = [track(entry, index) for index, entry in enumerate(entries, 1)]
    result.checks = [tracker.check for tracker in trackers]
    file_watch = _FileWatch(path) if path is not None else None
    state_file = None
    if resume:
        state_file = monitor_state.state_path(os.path.abspath(path) if path else source)
        saved = monitor_state.load(state_file)
        result.resumed = sum(
            t.resume(saved[monitor_state.key(t.check)])
            for t in trackers
            if monitor_state.key(t.check) in saved
        )

    # a scrape (another thread) must not see a run half applied
    lock = threading.Lock()
    servers = _serve(result, lock, metrics, status_page, clock)

    if live is None:
        live = sys.stdout.isatty()
    if not live:
        line_buffered()
    live = live and not quiet
    report = None
    if not (quiet or live):
        widths = monitor_view.change_widths(result)
        report = functools.partial(monitor_view.print_change, widths=widths)
    if not quiet:
        monitor_view.print_header(result)

    for tracker in trackers:
        tracker.due = result.started
    printed = 0

    def pending(tracker: _Tracker) -> bool:
        return rounds is None or tracker.runs < rounds

    def reload(watch: _FileWatch) -> None:
        nonlocal trackers, printed, report
        if live and printed:  # the message goes above the table
            clear_lines(printed)
            printed = 0
        try:
            loaded = load_config(watch.path)
            fresh = [track(entry, index) for index, entry in enumerate(loaded, 1)]
        except (ConfigError, OSError) as exc:
            if not quiet:
                warn(f"{watch.path} not reloaded, the checks keep running: {exc}")
            return
        with lock:
            trackers, added, removed = _merge(trackers, fresh, clock())
            result.checks = [tracker.check for tracker in trackers]
        for tracker in removed:
            if tracker.notifier is not None:
                tracker.notifier.flush()
        if report is not None:
            report = functools.partial(
                monitor_view.print_change, widths=monitor_view.change_widths(result)
            )
        if not quiet:
            monitor_view.print_reload(result, added, [t.check.name for t in removed], clock())

    saved_at = clock()

    def save_state() -> None:
        nonlocal state_file, saved_at, printed
        if state_file is None:
            return
        saved_at = clock()
        try:
            with lock:
                monitor_state.save(state_file, result.checks)
        except OSError as exc:
            if not quiet:
                if live and printed:
                    clear_lines(printed)
                    printed = 0
                warn(f"could not save the state of the checks: {exc}")
            state_file = None  # warn once

    try:
        while any(pending(tracker) for tracker in trackers):
            if file_watch is not None and file_watch.changed():
                reload(file_watch)
            if clock() - saved_at >= SAVE_EVERY:
                save_state()
            now = clock()
            ready = [tracker for tracker in trackers if pending(tracker) and tracker.due <= now]
            if ready:
                outcomes = run([tracker.entry for tracker in ready], workers)
                finished = clock()
                with lock:
                    for tracker, outcome in zip(ready, outcomes, strict=True):
                        tracker.apply(outcome, finished, report)
                        # the next run is due one interval after this one was;
                        # after a slow run, start from now instead of catching up
                        tracker.due = max(tracker.due + tracker.check.every, finished)
            if live:
                with lock:
                    printed = monitor_view.redraw(result, clock(), printed)
            waiting = [tracker.due for tracker in trackers if pending(tracker)]
            if not waiting:
                break
            pause = min(waiting) - clock()
            if file_watch is not None:
                pause = min(pause, RELOAD_CHECK)
            if live:
                pause = min(pause, 1.0)  # keep the "for" column ticking
            if pause > 0:
                sleep(pause)
    except KeyboardInterrupt:
        if not quiet:
            print()
    finally:
        save_state()
        for server in servers:
            server.stop()
        for tracker in trackers:
            if tracker.notifier is not None:
                tracker.notifier.flush()

    result.ended = clock()
    if not quiet:
        monitor_view.print_summary(result)
    return result
