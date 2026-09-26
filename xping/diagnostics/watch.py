"""Repeat a check until Ctrl-C (--watch) or until it passes (--until-up)."""

from __future__ import annotations

import time
from collections.abc import Callable

from xping.models.watch import WatchResult, WatchSample
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.views import watch as watch_view

Probe = Callable[[], tuple[bool, "float | None", str]]


def watch(
    target: str,
    check: str,
    probe: Probe,
    every: float = 2.0,
    until_up: bool = False,
    quiet: bool = False,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    notifier=None,
) -> WatchResult:
    """Run *probe* every *every* seconds.

    *probe* returns ``(ok, latency_ms, detail)``. In --until-up mode the
    function returns as soon as a check passes; otherwise it runs until
    Ctrl-C and then prints a summary. Ctrl-C in --until-up mode propagates
    (exit code 130) because the awaited state was never reached.
    *notifier* (see diagnostics.notify) is told about every up/down change.
    """
    result = WatchResult(target=target, check=check, until_up=until_up)
    if not quiet:
        mode = "WAIT FOR UP" if until_up else "WATCH"
        print(section_header(f"{check.upper()} {mode}  {target}", "◉"))
        print(kv("Target", c(target, BRAND_TEAL, BOLD)))
        print(kv("Every", f"{every:g}s"))
        print(kv("Stop", "when up" if until_up else "Ctrl-C"))
        print()

    try:
        return _loop(result, probe, every, until_up, quiet, clock, sleep, notifier)
    finally:
        if notifier is not None:
            notifier.flush()


def _loop(result, probe, every, until_up, quiet, clock, sleep, notifier) -> WatchResult:
    seq = 0
    try:
        while True:
            seq += 1
            started = clock()
            ok, latency, detail = probe()
            sample = WatchSample(seq=seq, ts=started, ok=ok, latency_ms=latency, detail=detail)
            previous = result.samples[-1] if result.samples else None
            result.samples.append(sample)
            if not quiet:
                watch_view.print_sample(sample, previous, result)
            if notifier is not None:
                notifier.observe(
                    ok,
                    previous.ok if previous else None,
                    detail,
                    latency,
                    final=until_up and ok,
                )
            if until_up and ok:
                if not quiet:
                    watch_view.print_up(result)
                return result
            remaining = every - (clock() - started)
            if remaining > 0:
                sleep(remaining)
    except KeyboardInterrupt:
        if until_up:
            raise
        if not quiet:
            watch_view.print_summary(result)
        return result
