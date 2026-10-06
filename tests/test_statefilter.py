"""Debounced up/down: fail_after / recover_after (monitor, watch, ping)."""

import json
from unittest.mock import patch

import pytest

from xping.diagnostics import monitor as monitor_diag
from xping.diagnostics.check import ConfigError
from xping.diagnostics.watch import watch
from xping.models.check import CheckOutcome
from xping.statefilter import StateFilter, outages


def _feed(f, results):
    return [f.update(ok) for ok in results]


def test_default_reports_every_change():
    f = StateFilter()
    assert _feed(f, [True, False, True]) == [True, True, True]


def test_one_blip_is_not_an_outage():
    f = StateFilter(fail_after=3)
    assert _feed(f, [True, False, True, False, False]) == [True, False, False, False, False]
    assert f.state is True and f.pending == (2, 3)
    assert f.update(False) and f.state is False and f.pending is None


def test_recovery_needs_a_streak_and_unknown_start_waits():
    f = StateFilter(fail_after=2, recover_after=2)
    assert _feed(f, [False]) == [False] and f.state is None  # not confirmed yet
    assert _feed(f, [False, True, False, True, True]) == [True, False, False, False, True]


def test_invalid_thresholds():
    with pytest.raises(ValueError):
        StateFilter(fail_after=0)


def test_outages_span_first_failure_to_first_good_run():
    results = [(0, True), (10, False), (20, True), (30, False), (40, False), (50, False),
               (60, True), (70, True), (80, False), (90, False), (100, False)]
    assert outages(results, fail_after=3, recover_after=2) == [(30, 60), (80, None)]
    assert len(outages(results)) == 3  # without debouncing every failure counts


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _monitor(tmp_path, results, **kwargs):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"checks": [{"name": "web", "type": "ping", "host": "a"}]}))
    plan = list(results)

    def run(entries, workers):
        ok = plan.pop(0)
        return [CheckOutcome("web", "ping", "a", ok, "ok" if ok else "lost", 1.0, None)]

    clock = Clock()
    return monitor_diag.monitor(
        str(path), every=10, rounds=len(results), clock=clock, sleep=clock.sleep, run=run,
        **kwargs,
    )


def test_monitor_alerts_only_on_confirmed_changes(tmp_path):
    sent = []
    with patch("xping.diagnostics.notify.desktop_notify", lambda t, m: sent.append(m) or True):
        result = _monitor(
            tmp_path, [True, True, False, True, False, False, False, True, True],
            fail_after=3, recover_after=2, notify=True, quiet=True,
        )
    web = result.checks[0]
    assert [m.split(" is ")[1].split()[0] for m in sent] == ["DOWN", "UP"]
    assert "after 40s" in sent[1]  # first failure of the outage -> UP confirmed
    assert web.outages == 1 and web.longest_outage_s == pytest.approx(30)  # to first good run
    assert web.up is True and result.ok
    assert web.up_pct == pytest.approx(5 / 9 * 100)  # uptime still counts every run


def test_monitor_unconfirmed_failure_at_the_end_is_not_down(tmp_path, capsys):
    result = _monitor(tmp_path, [True, False], fail_after=3, live=False)
    assert result.ok and result.checks[0].up is True
    live = capsys.readouterr().out.split("SUMMARY")[0]
    assert live.count(" UP ") == 1 and " DOWN " not in live


def test_monitor_per_check_keys_override_and_validate(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"checks": [{"type": "ping", "host": "a", "fail_after": 0}]}))
    with pytest.raises(ConfigError, match="fail_after"):
        monitor_diag.monitor(str(path), quiet=True)


def test_watch_until_up_waits_for_recover_after(capsys):
    results = iter([False, True, False, True, True, True])
    clock = Clock()
    result = watch(
        "h", "tcp", lambda: (next(results), 1.0, "x"), every=1, until_up=True, quiet=True,
        clock=clock, sleep=clock.sleep, recover_after=2,
    )
    assert [s.ok for s in result.samples] == [False, True, False, True, True]


def test_watch_notifies_after_fail_after():
    results = iter([True, False, False, True, False, False, False])
    events = []

    class N:
        def observe(self, ok, previous, detail, latency, final=False):
            events.append((ok, previous))

        def flush(self):
            pass

    def probe():
        try:
            return next(results), 1.0, "x"
        except StopIteration:
            raise KeyboardInterrupt from None

    clock = Clock()
    watch("h", "tcp", probe, quiet=True, clock=clock, sleep=clock.sleep, notifier=N(), fail_after=3)
    assert events == [(True, None), (False, True)]


def test_cli_flags():
    from xping.cli.parser import build_parser

    args = build_parser().parse_args(["tcp", "h", "22", "--watch", "--fail-after", "3"])
    assert args.fail_after == 3 and args.recover_after == 1
    assert build_parser().parse_args(["ping", "h", "--watch"]).fail_after is None  # live: 3
    args = build_parser().parse_args(["monitor", "f.toml", "--recover-after", "2"])
    assert args.recover_after == 2
    with pytest.raises(SystemExit):
        build_parser().parse_args(["http", "https://x", "--fail-after", "0"])
