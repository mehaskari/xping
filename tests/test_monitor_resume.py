"""xping monitor --resume: what a monitor keeps for the next one (fake clock,
fake checks, the state under a temporary directory)."""

import json
import os
import stat
import sys

import pytest

from xping.diagnostics import monitor as monitor_diag
from xping.diagnostics import monitor_state
from xping.models.check import CheckOutcome
from xping.models.monitor import SAVED_SAMPLES, MonitoredCheck, MonitorSample
from xping.models.ping import PingResult

GW = {"name": "gw", "type": "ping", "host": "h"}


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_state, "STATE_DIR", tmp_path / "state")
    return tmp_path / "state"


def _run(tmp_path, plan, clock=None, checks=(GW,), resume=True, **options):
    """One monitor over *plan* (ok values, one per run of each check)."""
    path = tmp_path / "mon.json"
    if not path.exists():
        path.write_text(json.dumps({"checks": list(checks)}))
    clock = clock or Clock()
    results = iter(plan)

    def run(entries, workers):
        out = []
        for e in entries:
            ok = next(results)
            ping = PingResult(host="h", ip="192.0.2.1", count=1, rtts=[10.0 if ok else -1.0])
            out.append(CheckOutcome(e["name"], e["type"], "h", ok, "fine" if ok else "bad", 1.0, ping))
        return out

    return monitor_diag.monitor(
        str(path),
        rounds=len(plan),
        every=10,
        quiet=True,
        clock=clock,
        sleep=clock.sleep,
        run=run,
        resume=resume,
        **options,
    )


def test_totals_go_on_and_rounds_count_only_this_monitor(tmp_path):
    first = _run(tmp_path, [True, False, True])
    second = _run(tmp_path, [True, True])
    assert first.resumed == 0
    assert second.resumed == 1
    check = second.checks[0]
    assert (check.checks, check.failures) == (5, 1)
    assert check.up_pct == 80.0
    assert check.outages == 1
    assert check.average == 10.0
    assert len(check.samples) == 5


def test_without_resume_nothing_is_read_or_written(tmp_path, state_dir):
    _run(tmp_path, [True, True])
    result = _run(tmp_path, [True], resume=False)
    assert result.checks[0].checks == 1
    other = tmp_path / "other"
    other.mkdir()
    _run(other, [True], resume=False)
    assert len(list(state_dir.iterdir())) == 1


def test_a_check_that_was_down_stays_down_without_alerting_again(tmp_path):
    clock = Clock()
    _run(tmp_path, [True, False, False], clock=clock)
    clock.now += 500  # monitor not running
    captured = {}
    original = monitor_diag.Notifier

    def spy(*args, **kwargs):
        captured["notifier"] = original(*args, **kwargs)
        return captured["notifier"]

    monitor_diag.Notifier = spy
    try:
        result = _run(tmp_path, [False, True], clock=clock, notify=True)
    finally:
        monitor_diag.Notifier = original
    sent = captured["notifier"].sent
    assert [event["event"] for event in sent] == ["up"]
    assert "again after" in sent[0]["text"]
    assert result.checks[0].outages == 1
    assert result.checks[0].up is True


def test_going_down_after_a_restart_alerts_on_the_first_failure(tmp_path, monkeypatch):
    _run(tmp_path, [True, True])
    sent = []
    monkeypatch.setattr(
        monitor_diag.Notifier, "event", lambda self, kind, *args, **kw: sent.append(kind)
    )
    _run(tmp_path, [False], notify=True)
    assert sent == ["down"]


def test_an_unchanged_state_keeps_its_old_since(tmp_path):
    clock = Clock()
    first = _run(tmp_path, [True, True], clock=clock)
    since = first.checks[0].since
    second = _run(tmp_path, [True], clock=clock)
    assert second.checks[0].since == since


def test_a_changed_target_starts_from_zero(tmp_path):
    _run(tmp_path, [True, True])
    (tmp_path / "mon.json").write_text(json.dumps({"checks": [{**GW, "host": "other"}]}))
    result = _run(tmp_path, [True])
    assert result.resumed == 0
    assert result.checks[0].checks == 1


@pytest.mark.parametrize("content", ["{ broken", "[]", '{"version": 99, "checks": {}}'])
def test_an_unusable_file_means_starting_from_zero(tmp_path, content):
    _run(tmp_path, [True])
    file = monitor_state.state_path(str(tmp_path / "mon.json"))
    file.write_text(content)
    result = _run(tmp_path, [True])
    assert (result.resumed, result.checks[0].checks) == (0, 1)


@pytest.mark.parametrize(
    "change",
    [
        {"runs": "many"},
        {"samples": [[1.0]]},
        {"samples": [[1.0, True, "fast"]]},
        {"spans": [["x", None]]},
        {"up": "yes"},
        {"since": "now"},
    ],
)
def test_a_damaged_check_leaves_it_as_it_was(change):
    check = MonitoredCheck(name="a", type="tcp", target="h", every=1)
    check.record(MonitorSample(ts=1.0, ok=True))
    state = {**check.export_state(), **change}
    with pytest.raises((KeyError, TypeError, ValueError)):
        check.restore_state(state)
    assert check.checks == 1


def test_only_the_latest_runs_are_saved():
    check = MonitoredCheck(name="a", type="tcp", target="h", every=1)
    for i in range(SAVED_SAMPLES + 50):
        check.record(MonitorSample(ts=float(i), ok=True))
    assert len(check.export_state()["samples"]) == SAVED_SAMPLES


def test_saved_while_running_not_only_at_the_end(tmp_path, monkeypatch):
    saves = []
    real = monitor_state.save
    monkeypatch.setattr(
        monitor_state, "save", lambda path, checks: (saves.append(checks[0].checks), real(path, checks))
    )
    _run(tmp_path, [True] * 13)  # 120 s of runs, one every 10 s
    assert len(saves) >= 3
    assert saves[-1] == 13


def test_a_run_that_blows_up_keeps_what_was_done(tmp_path):
    _run(tmp_path, [True])
    clock = Clock()

    def run(entries, workers):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        monitor_diag.monitor(
            str(tmp_path / "mon.json"),
            rounds=1,
            quiet=True,
            clock=clock,
            sleep=clock.sleep,
            run=run,
            resume=True,
        )
    assert _run(tmp_path, [True]).checks[0].checks == 2


def test_an_unwritable_state_warns_once_and_monitor_goes_on(tmp_path, monkeypatch, capsys):
    def fail(path, checks):
        raise OSError("read-only")

    monkeypatch.setattr(monitor_state, "save", fail)
    path = tmp_path / "mon.json"
    path.write_text(json.dumps({"checks": [GW]}))
    clock = Clock()
    run = lambda entries, workers: [  # noqa: E731
        CheckOutcome("gw", "ping", "h", True, "ok", 1.0, None) for _ in entries
    ]
    result = monitor_diag.monitor(
        str(path), rounds=9, every=30, live=False, clock=clock, sleep=clock.sleep, run=run, resume=True
    )
    assert result.checks[0].checks == 9
    assert capsys.readouterr().out.count("could not save the state") == 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_the_file_is_private_and_nothing_is_left_behind(tmp_path, state_dir):
    _run(tmp_path, [True])
    files = list(state_dir.iterdir())
    assert len(files) == 1 and files[0].suffix == ".json"
    assert stat.S_IMODE(os.stat(files[0]).st_mode) == 0o600


def test_two_sources_have_their_own_files():
    assert monitor_state.state_path("a") != monitor_state.state_path("b")


def test_the_header_says_it_resumed(tmp_path, capsys):
    _run(tmp_path, [True])
    path = tmp_path / "mon.json"
    clock = Clock()
    run = lambda entries, workers: [  # noqa: E731
        CheckOutcome("gw", "ping", "h", True, "ok", 1.0, None) for _ in entries
    ]
    monitor_diag.monitor(
        str(path), rounds=1, live=False, clock=clock, sleep=clock.sleep, run=run, resume=True
    )
    assert "1 of 1 checks" in capsys.readouterr().out
