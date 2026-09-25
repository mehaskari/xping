"""Exit codes, --quiet, and threshold verdicts."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.cli.verdict import evaluate
from xping.models.dnscheck import DnsCheckResult
from xping.models.health import HealthResult
from xping.models.http import HttpResult
from xping.models.mtr import MtrHop, MtrResult
from xping.models.ping import PingResult
from xping.models.tcp import TcpAttempt, TcpResult
from xping.models.tls import TlsResult
from xping.models.trace import Hop


def _opts(**kw):
    return SimpleNamespace(**kw)


# ── verdicts ──────────────────────────────────────────────────────────────────


class TestPingVerdict:
    def test_healthy(self):
        assert evaluate(PingResult(host="h", ip="1.1.1.1", count=4, rtts=[10.0] * 4)) == []

    def test_unreachable(self):
        failures = evaluate(PingResult(host="h", ip="1.1.1.1", count=2, rtts=[-1.0, -1.0]))
        assert failures and not failures[0].threshold

    def test_unresolved(self):
        assert evaluate(PingResult(host="nope", ip="?", count=4, resolved=False))

    def test_loss_threshold(self):
        r = PingResult(host="h", ip="1.1.1.1", count=4, rtts=[10.0, -1.0, 10.0, 10.0])
        assert evaluate(r) == []
        failures = evaluate(r, _opts(max_loss=10))
        assert failures[0].threshold and "25.0%" in failures[0].message
        assert evaluate(r, _opts(max_loss=25)) == []

    def test_latency_threshold(self):
        r = PingResult(host="h", ip="1.1.1.1", count=2, rtts=[150.0, 250.0])
        assert evaluate(r, _opts(max_latency=100))[0].threshold
        assert evaluate(r, _opts(max_latency=300)) == []


class TestOtherVerdicts:
    def test_tcp(self):
        ok = TcpResult(host="h", port=443, ip="1.2.3.4", attempts=[TcpAttempt(1, True, 20.0)])
        down = TcpResult(host="h", port=443, ip="1.2.3.4", attempts=[TcpAttempt(1, False, 5.0)])
        assert evaluate(ok) == []
        assert evaluate(down)
        assert evaluate(ok, _opts(max_latency=10))[0].threshold

    def test_trace(self):
        assert evaluate([]) and evaluate([Hop(ttl=1, host=None, ip="10.0.0.1")]) == []

    def test_http(self):
        assert evaluate(HttpResult(url="u", status_code=200, total_ms=50.0)) == []
        assert evaluate(HttpResult(url="u", status_code=503))
        assert evaluate(HttpResult(url="u", error="Request timed out"))
        assert evaluate(HttpResult(url="u", status_code=301), _opts(expect_status=200))
        assert evaluate(HttpResult(url="u", status_code=404), _opts(expect_status=404)) == []
        assert evaluate(HttpResult(url="u", status_code=200, total_ms=900.0), _opts(max_latency=500))

    def test_tls(self):
        future = TlsResult(host="h", port=443, not_after="Jan  1 00:00:00 2099 GMT")
        past = TlsResult(host="h", port=443, not_after="Jan  1 00:00:00 2001 GMT")
        assert evaluate(future) == []
        assert evaluate(past)
        assert evaluate(future, _opts(min_days=10**6))[0].threshold
        assert evaluate(TlsResult(host="h", port=443, error="refused"))

    def test_scores(self):
        assert evaluate(HealthResult(host="h", score=60)) == []
        assert evaluate(HealthResult(host="h", score=60), _opts(min_score=80))[0].threshold
        assert evaluate(HealthResult(host="h", resolved=False))
        assert evaluate(DnsCheckResult(domain="d", score=40), _opts(min_score=50))

    def test_mtr_destination(self):
        dest = MtrHop(ttl=2, ip="9.9.9.9", rtts=[10.0, -1.0])
        r = MtrResult(host="h", dest_ip="9.9.9.9", hops=[MtrHop(ttl=1, ip="10.0.0.1"), dest])
        assert evaluate(r) == []
        assert evaluate(r, _opts(max_loss=20))[0].threshold
        silent = MtrResult(host="h", dest_ip="9.9.9.9", hops=[MtrHop(ttl=1, ip="10.0.0.1")])
        assert evaluate(silent)

    def test_profile_and_misc(self):
        assert evaluate(None) == [] and evaluate(True) == []
        assert evaluate(False)


# ── main() exit codes ─────────────────────────────────────────────────────────


def _run_main(argv, result):
    from xping.cli.main import _DISPATCH, main

    command = argv[0]
    with patch("sys.argv", ["xping", *argv]):
        with patch.dict(_DISPATCH, {command: lambda _args: result}):
            with pytest.raises(SystemExit) as exc:
                main()
    return exc.value.code


class TestMainExitCodes:
    def test_success_is_zero(self):
        r = PingResult(host="h", ip="1.1.1.1", count=1, rtts=[5.0])
        assert _run_main(["ping", "h"], r) == 0

    def test_failure_is_one(self):
        r = PingResult(host="h", ip="1.1.1.1", count=1, rtts=[-1.0])
        assert _run_main(["ping", "h"], r) == 1

    def test_threshold_reason_on_stderr(self, capsys):
        r = PingResult(host="h", ip="1.1.1.1", count=1, rtts=[500.0])
        assert _run_main(["ping", "h", "--max-latency", "100"], r) == 1
        assert "--max-latency" in capsys.readouterr().err

    def test_quiet_suppresses_reason(self, capsys):
        r = PingResult(host="h", ip="1.1.1.1", count=1, rtts=[500.0])
        assert _run_main(["ping", "h", "--max-latency", "100", "-q"], r) == 1
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""

    def test_watch_with_quiet_is_usage_error(self):
        from xping.cli.main import main

        with patch("sys.argv", ["xping", "ping", "h", "--watch", "--quiet"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2


class TestQuietFlag:
    def test_quiet_runs_diagnostic_silently(self, capsys):
        from xping.cli import commands

        args = build_parser().parse_args(["ping", "example.com", "-q"])
        r = PingResult(host="example.com", ip="1.2.3.4", count=1, rtts=[3.0])
        with patch("xping.cli.commands.ping", return_value=r) as fake:
            assert commands.cmd_ping(args) is r
        assert fake.call_args.kwargs["quiet"] is True
        assert capsys.readouterr().out == ""

    def test_output_formats_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["ping", "h", "--json", "--quiet"])

    @pytest.mark.parametrize("value", ["-1", "abc"])
    def test_threshold_validation(self, value):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["ping", "h", "--max-loss", value])

    def test_score_range(self):
        assert build_parser().parse_args(["health", "h", "--min-score", "0"]).min_score == 0
        with pytest.raises(SystemExit):
            build_parser().parse_args(["health", "h", "--min-score", "101"])
