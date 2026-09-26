"""xping diff — compare two --json results."""

import json
import sys

import pytest

from xping.cli.parser import build_parser
from xping.cli.verdict import evaluate
from xping.diagnostics import diff as d
from xping.exporters.csv import export_csv
from xping.exporters.json import export_json
from xping.models.ping import PingResult


def _ping(rtts):
    return json.loads(export_json(PingResult("h", "1.2.3.4", len(rtts), rtts)))


def _metric(result, label):
    return next(m for m in result.metrics if m.label == label)


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        ([{"ttl": 1, "ip": "10.0.0.1"}], "trace"),
        ({"rtts": [], "loss_pct": 0}, "ping"),
        ({"status_code": 200, "url": "u"}, "http"),
        ({"outcomes": []}, "check"),
        ({"steps": [], "diagnosis": ""}, "doctor"),
        ({"checks": [], "score": 1, "domain": "d"}, "dnscheck"),
        ({"checks": [], "kind": "ip", "target": "t"}, "blocklist"),
        ({"hops": [], "dest_ip": "x"}, "mtr"),
        ({"current": None, "nearby": []}, "wifi"),
        ({"ipv4": [], "ipv6": [], "ns": []}, "lookup"),
        ({"something": 1}, "generic"),
    ],
)
def test_detect(data, kind):
    assert d.detect(data) == kind


def test_ping_better_and_worse():
    result = d.compare(_ping([20.0, 22.0, 21.0]), _ping([40.0, -1.0, 44.0]))
    avg, loss = _metric(result, "Average RTT"), _metric(result, "Packet loss")
    assert avg.verdict == "worse" and round(avg.change_pct) == 100
    assert loss.verdict == "worse" and loss.after == pytest.approx(33.33, abs=0.01)
    assert result.worse >= 2 and evaluate(result) == []  # no --max-regression: report only


def test_noise_is_same():
    result = d.compare(_ping([100.0, 100.0]), _ping([101.5, 102.0]))
    assert _metric(result, "Average RTT").verdict == "same"


def test_max_regression_gate():
    before, after = _ping([20.0, 20.0]), _ping([26.0, 26.0])  # +30 %
    assert evaluate(d.compare(before, after, max_regression=50)) == []
    failures = evaluate(d.compare(before, after, max_regression=10))
    assert failures and failures[0].threshold and "Average RTT +30%" in failures[0].message


def test_status_changes_are_regressions():
    before = {"domain": "d", "score": 90, "checks": [{"name": "DMARC", "status": "ok"}, {"name": "DKIM", "status": "info"}]}
    after = {"domain": "d", "score": 70, "checks": [{"name": "DMARC", "status": "fail"}, {"name": "DKIM", "status": "ok"}]}
    result = d.compare(before, after, max_regression=100)
    assert "check DMARC: ok → fail" in result.regressions
    assert "check DKIM: info → ok" in result.changes and "check DKIM: info → ok" not in result.regressions
    assert _metric(result, "DNS score").verdict == "worse"


def test_check_report_outcomes():
    before = {"outcomes": [{"name": "DB", "ok": True}], "passed": 1, "failed": 0}
    after = {"outcomes": [{"name": "DB", "ok": False}], "passed": 0, "failed": 1}
    assert "check DB: pass → fail" in d.compare(before, after).regressions


def test_trace_route_change():
    before = [{"ttl": 1, "ip": "10.0.0.1", "avg_rtt": 1.0}, {"ttl": 2, "ip": "192.0.2.1", "avg_rtt": 20.0}]
    after = [{"ttl": 1, "ip": "10.0.0.1", "avg_rtt": 1.0}, {"ttl": 2, "ip": "198.51.100.9", "avg_rtt": 45.0}]
    result = d.compare(before, after)
    assert result.changes[0] == "route changed from hop 2 on"
    assert "hop 2: 192.0.2.1 → 198.51.100.9" in result.changes
    assert _metric(result, "Final hop RTT").verdict == "worse"


def test_lookup_sets_and_scalars():
    before = {"ipv4": ["1.1.1.1"], "ipv6": [], "ns": ["a"], "mx": [[10, "mx1"]], "cname": None}
    after = {"ipv4": ["2.2.2.2"], "ipv6": [], "ns": ["a"], "mx": [[10, "mx1"], [20, "mx2"]], "cname": "cdn"}
    changes = d.compare(before, after).changes
    assert "+ A 2.2.2.2" in changes and "− A 1.1.1.1" in changes and "+ MX 20 mx2" in changes
    assert "CNAME: — → cdn" in changes


def test_mixed_kinds_and_generic():
    assert "cannot compare a ping result with a http result" in d.compare(
        _ping([1.0]), {"status_code": 200, "url": "u"}
    ).error
    generic = d.compare({"a": 1, "b": "x"}, {"a": 5, "b": "y"})
    assert generic.kind == "generic" and generic.metrics[0].label == "a"


def test_files_stdin_and_errors(tmp_path, monkeypatch, capsys):
    import io

    old = tmp_path / "old.json"
    old.write_text(json.dumps(_ping([10.0, 10.0])))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_ping([30.0, 30.0]))))
    result = d.diff(str(old), "-", quiet=True)
    assert result.before.startswith(str(old)) and result.after == "stdin"
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(ValueError, match="not an xping --json file"):
        d.diff(str(old), str(bad), quiet=True)
    with pytest.raises(ValueError, match="cannot read"):
        d.diff(str(old), str(tmp_path / "missing.json"), quiet=True)
    with pytest.raises(ValueError, match="only one side"):
        d.diff("-", "-", quiet=True)


def test_render_and_exports(capsys):
    from unittest.mock import patch

    from xping.render.views import diff as view

    result = d.compare(_ping([20.0, 20.0]), _ping([40.0, 40.0]), max_regression=10)
    result.before, result.after = "a.json", "b.json"
    with patch("xping.render.COLOR", False), patch("xping.render.ansi.COLOR", False):
        view.print_result(result)
    out = capsys.readouterr().out
    assert "▼ worse" in out and "regression(s) beyond 10%" in out
    assert export_csv(result).splitlines()[0] == "metric,before,after,unit,change_pct,verdict"
    assert json.loads(export_json(result))["worse"] >= 1


def test_parser_and_cli_usage_error(tmp_path):
    from xping.cli import commands
    from xping.cli.errors import UsageError

    args = build_parser().parse_args(["diff", "a.json", "-", "--max-regression", "25"])
    assert (args.before, args.after, args.max_regression) == ("a.json", "-", 25.0)
    with pytest.raises(UsageError, match="cannot read"):
        commands.cmd_diff(build_parser().parse_args(["diff", str(tmp_path / "x"), str(tmp_path / "y")]))
