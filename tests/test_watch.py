"""--watch / --until-up for tcp, http and health."""

from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.cli.verdict import evaluate
from xping.diagnostics.watch import watch
from xping.models.tcp import TcpAttempt, TcpResult
from xping.models.watch import WatchResult, WatchSample


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _probes(states, interrupt_after=None):
    calls = {"n": 0}

    def probe():
        i = calls["n"]
        calls["n"] += 1
        if interrupt_after is not None and i >= interrupt_after:
            raise KeyboardInterrupt
        ok = states[i]
        return ok, 12.0 if ok else None, "connected" if ok else "refused"

    return probe


def test_until_up_returns_on_first_success(capsys):
    clock = FakeClock()
    with patch("xping.render.COLOR", False):
        result = watch("db:5432", "tcp", _probes([False, False, True]), every=5, until_up=True,
                       clock=clock, sleep=clock.sleep)
    assert result.checks == 3 and result.last_ok and evaluate(result) == []
    out = capsys.readouterr().out
    assert "▲ UP after 10s" in out and "db:5432 is up" in out


def test_until_up_ctrl_c_propagates():
    clock = FakeClock()
    with pytest.raises(KeyboardInterrupt):
        watch("h", "tcp", _probes([False, False], interrupt_after=2), until_up=True,
              quiet=True, clock=clock, sleep=clock.sleep)


def test_watch_summary_and_transitions(capsys):
    clock = FakeClock()
    with patch("xping.render.COLOR", False):
        result = watch("h", "http", _probes([True, False, False, True], interrupt_after=4),
                       every=10, clock=clock, sleep=clock.sleep)
    assert result.transitions == 2 and result.up_pct == 50.0
    assert result.longest_outage_s == 20.0 and evaluate(result) == []
    out = capsys.readouterr().out
    assert "▼ DOWN" in out and "UP again after 20s of downtime" in out and "Checks" in out


def test_watch_ending_down_fails_exit_code():
    r = WatchResult(target="h", check="tcp", samples=[WatchSample(1, 0.0, True), WatchSample(2, 5.0, False)])
    assert evaluate(r) and r.longest_outage_s == 0.0


def test_cmd_tcp_until_up_uses_verdict_and_thresholds():
    from xping.cli import commands

    args = build_parser().parse_args(
        ["tcp", "db", "5432", "--until-up", "-q", "--max-latency", "50", "--every", "0.5"]
    )
    slow = TcpResult(host="db", port=5432, ip="10.0.0.5", attempts=[TcpAttempt(1, True, 90.0)])
    fast = TcpResult(host="db", port=5432, ip="10.0.0.5", attempts=[TcpAttempt(1, True, 9.0)])
    with (
        patch("xping.cli.commands.tcp", side_effect=[slow, fast]) as fake_tcp,
        patch("xping.diagnostics.watch.time.sleep"),
    ):
        result = commands.cmd_tcp(args)
    assert fake_tcp.call_count == 2 and fake_tcp.call_args.kwargs["count"] == 1
    assert [s.ok for s in result.samples] == [False, True]
    assert "exceeds --max-latency" in result.samples[0].detail


@pytest.mark.parametrize(
    "argv",
    [
        ["tcp", "h", "80", "--watch", "--json"],
        ["http", "https://h", "--watch", "--quiet"],
        ["health", "h", "--until-up", "--csv"],
    ],
)
def test_watch_rejects_incompatible_output(argv):
    from xping.cli.main import main

    with patch("sys.argv", ["xping", *argv]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 2


def test_every_must_be_positive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["tcp", "h", "80", "--watch", "--every", "0"])
