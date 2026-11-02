"""xping monitor --metrics: the Prometheus text format, the listen address,
the HTTP endpoint and its wiring into monitor (fake checks, a real socket
on 127.0.0.1 with a free port)."""

import json
import re
import socket
import urllib.error
import urllib.request

import pytest

from xping.cli.parser import build_parser
from xping.diagnostics import monitor as monitor_diag
from xping.diagnostics import service
from xping.exporters import prometheus
from xping.models.check import CheckOutcome
from xping.models.monitor import MonitoredCheck, MonitorResult, MonitorSample
from xping.models.ping import PingResult

# one sample line: name{labels} value
SAMPLE = re.compile(r'^[a-z_]+(\{([a-z_]+="([^"\\]|\\.)*",?)*\})? (-?[0-9.e+]+|NaN|[+-]Inf)$')


def _result() -> MonitorResult:
    web = MonitoredCheck(
        name='Web "prod"\\eu',
        type="http",
        target="https://example.net",
        every=30,
        metric="Total",
        unit="ms",
        up=True,
        since=1000.0,
        samples=[
            MonitorSample(ts=1000.0, ok=True, value=120.0),
            MonitorSample(ts=1030.0, ok=False),
            MonitorSample(ts=1060.0, ok=True, value=80.5),
        ],
    )
    cert = MonitoredCheck(
        name="Cert",
        type="tls",
        target="example.net:443",
        every=3600,
        metric="Days left",
        unit="days",
        up=False,
        since=1050.0,
        samples=[MonitorSample(ts=1050.0, ok=False, value=3.0)],
    )
    waiting = MonitoredCheck(name="New", type="dns", target="example.net", every=60)
    return MonitorResult(source="checks.toml", started=990.0, checks=[web, cert, waiting])


def _series(text: str) -> dict[str, str]:
    return {
        line.rsplit(" ", 1)[0]: line.rsplit(" ", 1)[1]
        for line in text.splitlines()
        if line and not line.startswith("#")
    }


def test_every_line_is_valid_exposition_format():
    text = prometheus.render(_result())
    assert text.endswith("\n")
    for line in text.splitlines():
        if line.startswith("# HELP ") or line.startswith("# TYPE "):
            continue
        assert SAMPLE.match(line), line


def test_each_family_has_help_and_type_once_before_its_samples():
    text = prometheus.render(_result())
    seen = []
    for line in text.splitlines():
        if line.startswith("# TYPE "):
            name = line.split()[2]
            assert name not in seen
            seen.append(name)
        elif not line.startswith("#"):
            assert line.split("{")[0].split(" ")[0] == seen[-1]
    assert "xping_check_up" in seen and "xping_build_info" in seen


def test_values_states_and_counters():
    series = _series(prometheus.render(_result()))
    web = 'check="Web \\"prod\\"\\\\eu",type="http",target="https://example.net"'
    cert = 'check="Cert",type="tls",target="example.net:443"'
    assert series[f"xping_check_up{{{web}}}"] == "1"
    assert series[f"xping_check_up{{{cert}}}"] == "0"
    assert series[f"xping_check_runs_total{{{web}}}"] == "3"
    assert series[f"xping_check_failures_total{{{web}}}"] == "1"
    assert series[f'xping_check_value{{{web},metric="Total",unit="ms"}}'] == "80.5"
    assert series[f"xping_check_latency_seconds{{{web}}}"] == "0.0805"
    assert series[f'xping_check_value{{{cert},metric="Days left",unit="days"}}'] == "3"
    assert series[f"xping_check_state_change_timestamp_seconds{{{cert}}}"] == "1050"
    assert series[f"xping_check_interval_seconds{{{cert}}}"] == "3600"
    assert series["xping_monitor_start_time_seconds"] == "990"


def test_a_check_without_data_has_no_made_up_values():
    series = _series(prometheus.render(_result()))
    new = 'check="New",type="dns",target="example.net"'
    assert f"xping_check_up{{{new}}}" not in series
    assert f"xping_check_last_run_ok{{{new}}}" not in series
    assert series[f"xping_check_runs_total{{{new}}}"] == "0"
    # only time-valued checks get the latency metric
    assert not any(k.startswith('xping_check_latency_seconds{check="Cert"') for k in series)


def test_label_values_cannot_break_out():
    check = MonitoredCheck(name='a"b\nc}d', type="tcp", target="h:1", every=1)
    text = prometheus.render(MonitorResult(source="x", started=0.0, checks=[check]))
    line = next(x for x in text.splitlines() if x.startswith("xping_check_runs_total"))
    assert line == 'xping_check_runs_total{check="a\\"b\\nc}d",type="tcp",target="h:1"} 0'
    assert "\nc}" not in text


@pytest.mark.parametrize(
    "text, expected",
    [
        ("9101", ("127.0.0.1", 9101)),
        (":9101", ("127.0.0.1", 9101)),
        ("0.0.0.0:9101", ("0.0.0.0", 9101)),
        ("localhost:80", ("localhost", 80)),
        ("[::1]:9101", ("::1", 9101)),
        ("[::]:9101", ("::", 9101)),
    ],
)
def test_parse_listen(text, expected):
    assert prometheus.parse_listen(text) == expected
    host, port = expected
    assert prometheus.parse_listen(prometheus.format_listen(host, port)) == expected


@pytest.mark.parametrize("text", ["", "abc", ":0", ":70000", "::1:9101", "host:"])
def test_parse_listen_rejects(text):
    with pytest.raises(prometheus.ListenError):
        prometheus.parse_listen(text)


def test_cli_option_parses_and_rejects():
    parser = build_parser()
    args = parser.parse_args(["monitor", "example.net", "--metrics", ":9101"])
    assert args.metrics == ("127.0.0.1", 9101)
    assert parser.parse_args(["monitor", "example.net"]).metrics is None
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["monitor", "example.net", "--metrics", "nope"])
    assert exc.value.code == 2


def test_service_keeps_the_metrics_option():
    parser = build_parser()
    args = parser.parse_args(["monitor", "example.net", "--metrics", "[::1]:9200"])
    assert service.monitor_arguments(args)[-2:] == ["--metrics", "[::1]:9200"]
    plain = parser.parse_args(["monitor", "example.net"])
    assert "--metrics" not in service.monitor_arguments(plain)


def _get(url: str) -> tuple[int, str, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.headers["Content-Type"], resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers["Content-Type"], exc.read().decode()


def test_server_serves_metrics_and_404():
    server = prometheus.MetricsServer("127.0.0.1", 0, lambda: "xping_build_info 1\n").start()
    try:
        host, port = server.address
        status, kind, body = _get(f"http://{host}:{port}/metrics")
        assert (status, body) == (200, "xping_build_info 1\n")
        assert kind == prometheus.CONTENT_TYPE
        assert _get(f"http://{host}:{port}/metrics?x=1")[0] == 200
        assert _get(f"http://{host}:{port}/other")[0] == 404
    finally:
        server.stop()


def test_a_busy_port_is_a_clear_error():
    first = prometheus.MetricsServer("127.0.0.1", 0, lambda: "").start()
    try:
        port = first.address[1]
        with pytest.raises(prometheus.ListenError, match=f"127.0.0.1:{port}"):
            prometheus.MetricsServer("127.0.0.1", port, lambda: "")
    finally:
        first.stop()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_monitor_serves_its_checks_while_running(tmp_path):
    path = tmp_path / "mon.json"
    path.write_text(json.dumps({"checks": [{"name": "gw", "type": "ping", "host": "h"}]}))
    url = f"http://127.0.0.1:{_free_port()}/metrics"
    scraped = []

    def run(entries, workers):
        # scrape before each run, as Prometheus would, from another thread
        scraped.append(_get(url)[2])
        result = PingResult(host="h", ip="192.0.2.1", count=1, rtts=[12.0])
        return [CheckOutcome(e["name"], e["type"], "h", True, "ok", 1.0, result) for e in entries]

    now = [1_000_000.0]  # a fake clock: sleeping only moves it forward

    result = monitor_diag.monitor(
        str(path),
        rounds=3,
        quiet=True,
        clock=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        run=run,
        metrics=prometheus.parse_listen(url.split("/")[2]),
    )
    assert result.metrics_url == url
    assert len(scraped) == 3
    assert 'xping_check_runs_total{check="gw",type="ping",target="h"} 0' in scraped[0]
    assert 'xping_check_runs_total{check="gw",type="ping",target="h"} 2' in scraped[-1]
    assert 'xping_check_latency_seconds{check="gw",type="ping",target="h"} 0.012' in scraped[-1]
    # the server is gone once monitor returns
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(url, timeout=2)
