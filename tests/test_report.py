"""xping report — the saved history as one self-contained HTML page."""

import importlib
import json
import re
from unittest.mock import patch

import pytest

from xping.diagnostics import history
from xping.diagnostics.report import build
from xping.exporters.html_report import to_html
from xping.models.ping import PingResult
from xping.models.tcp import TcpAttempt, TcpResult


@pytest.fixture
def base(tmp_path, monkeypatch):
    base = tmp_path / "hist"
    monkeypatch.setattr(history, "HISTORY_DIR", base)
    with patch("xping.diagnostics.history.time.time") as clock:
        for i, rtt in enumerate([10.0, 12.0, -1.0, -1.0, 11.0, 13.0]):
            clock.return_value = 1_000_000 + i * 60
            result = PingResult("h", "192.0.2.1", 1, [rtt])
            history.record("ping", "1.1.1.1", result, rtt >= 0, base=base)
        for i in range(3):
            clock.return_value = 1_000_000 + i * 60
            tcp = TcpResult(host="db", port=5432, ip="10.0.0.5", attempts=[TcpAttempt(1, True, 3.0)])
            history.record("tcp", "db<script>:5432", tcp, True, base=base)
    return base


def test_build_summarises_every_target(base):
    report = build(base=base, now=1_000_400)
    assert [(s.command, s.target) for s in report.series] == [
        ("ping", "1.1.1.1"), ("tcp", "db<script>:5432"),
    ]
    ping = report.series[0]
    assert ping.metric == "Average RTT" and ping.unit == "ms" and ping.runs == 6
    assert ping.up_pct == pytest.approx(4 / 6 * 100)
    assert [(o.start, o.end) for o in ping.outages] == [(1_000_120, 1_000_240)]
    assert ping.latest == 13.0 and ping.median == pytest.approx(11.5)
    assert report.runs == 9 and report.error is None


def test_build_filters_and_limits(base):
    assert [s.target for s in build("tcp", base=base).series] == ["db<script>:5432"]
    assert build("ping", "1.1.1.1", last=2, base=base).series[0].runs == 2
    recent = build(since=150, base=base, now=1_000_300)
    assert recent.series[0].runs == 3 and recent.since == 1_000_150
    assert build("ping", "nope", base=base).error.startswith("no saved runs for ping nope")


def test_html_is_self_contained_and_escaped(base):
    page = to_html(build(base=base, now=1_000_400), title="Lab <net>")
    assert page.startswith("<!doctype html>") and "<title>Lab &lt;net&gt;</title>" in page
    assert "<script" not in page.lower().replace("&lt;script", "")
    assert not re.search(r'(src|href)="(https?:)?//', page)  # nothing loaded from the network
    assert "db&lt;script&gt;:5432" in page
    assert page.count("<svg") == 2 and 'class="outage"' in page and 'class="fail"' in page
    assert "prefers-color-scheme:dark" in page


def _main(argv, capsys):
    main_mod = importlib.import_module("xping.cli.main")
    with patch("sys.argv", ["xping", *argv]), pytest.raises(SystemExit) as exc:
        main_mod.main()
    return exc.value.code, capsys.readouterr()


def test_cli_writes_the_page(base, tmp_path, capsys):
    out = tmp_path / "r.html"
    code, captured = _main(["report", "-o", str(out), "--title", "Home"], capsys)
    assert code == 0 and "<title>Home</title>" in out.read_text()
    assert "wrote" in captured.out and "2 targets, 9 runs" in captured.out


def test_cli_stdout_json_and_errors(base, tmp_path, capsys):
    code, captured = _main(["report", "ping", "-o", "-"], capsys)
    assert code == 0 and captured.out.startswith("<!doctype html>")
    code, captured = _main(["report", "-o", str(tmp_path / "r.html"), "--json"], capsys)
    data = json.loads(captured.out)
    assert code == 0 and data["runs"] == 9 and data["path"].endswith("r.html")
    code, _ = _main(["report", "tcp", "missing"], capsys)
    assert code == 1
    code, _ = _main(["report", "--since", "soon"], capsys)
    assert code == 2


def test_chart_breaks_the_line_across_gaps_without_runs():
    from xping.exporters.html_report import _chart
    from xping.models.report import ReportPoint, ReportSeries

    times = [0, 10, 20, 30, 400, 410, 420]  # nothing ran between 30 and 400
    series = ReportSeries("ping", "h", "Average RTT", "ms",
                          [ReportPoint(t, True, 10.0 + i) for i, t in enumerate(times)])
    svg = _chart(series)
    assert svg.count("<polyline") == 2  # two measured stretches, not one line
