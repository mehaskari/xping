"""xping monitor --status-page: the page, its JSON, and how it shares the
HTTP server with --metrics (fake checks, real sockets on 127.0.0.1)."""

import json
import socket
import urllib.error
import urllib.request

import pytest

from xping.cli.parser import build_parser
from xping.diagnostics import monitor as monitor_diag
from xping.diagnostics import service
from xping.exporters import prometheus, status_page
from xping.models.check import CheckOutcome
from xping.models.monitor import MonitoredCheck, MonitorResult, MonitorSample
from xping.models.ping import PingResult

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url: str, method: str = "GET"):
    request = urllib.request.Request(url, method=method)
    try:
        with _DIRECT.open(request, timeout=5) as resp:
            return resp.status, resp.headers, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read().decode()


def _check(name="web", samples=(), **fields) -> MonitoredCheck:
    return MonitoredCheck(
        name=name,
        type="http",
        target="https://example.net",
        every=30,
        metric="Total",
        unit="ms",
        samples=list(samples),
        **fields,
    )


def _result(*checks) -> MonitorResult:
    return MonitorResult(source="checks.toml", started=1000.0, checks=list(checks))


def test_all_up():
    check = _check(samples=[MonitorSample(ts=1030.0, ok=True, value=120.0)], up=True, since=1030.0)
    page = status_page.render(_result(check), now=1090.0)
    assert page.startswith("<!doctype html>")
    assert "All checks up" in page
    assert ">UP<" in page
    assert "120.0 ms" in page and "100.00% up" in page and "for 1m" in page
    assert f'content="{status_page.REFRESH}"' in page  # reloads itself
    assert "Recent outages" not in page


def test_nothing_ran_yet():
    page = status_page.render(_result(_check()), now=1000.0)
    assert "Waiting for the first runs" in page
    assert ">WAITING<" in page


def test_failed_run_before_it_counts_as_down():
    check = _check(
        samples=[MonitorSample(ts=1030.0, ok=True), MonitorSample(ts=1060.0, ok=False)],
        fail_after=3,
        up=True,
        since=1030.0,
    )
    page = status_page.render(_result(check), now=1060.0)
    assert "Some checks are failing" in page
    assert ">FAILING<" in page


def test_a_down_check_is_counted_and_its_outage_listed():
    down = _check(
        name="db",
        samples=[MonitorSample(ts=1030.0, ok=False)],
        up=False,
        since=1030.0,
    )
    page = status_page.render(_result(down, _check(name="new")), now=1090.0)
    assert "1 of 2 checks down" in page
    assert ">DOWN<" in page
    assert "Recent outages" in page
    assert "1m so far" in page


def test_a_finished_outage_has_its_duration():
    check = _check(
        samples=[
            MonitorSample(ts=1000.0, ok=False),
            MonitorSample(ts=1090.0, ok=True),
        ],
    )
    page = status_page.render(_result(check), now=2000.0)
    assert "<td>1m30s</td>" in page


def test_everything_from_a_check_is_escaped():
    check = _check(name='<script>alert("x")</script>', detail="<img src=x>")
    page = status_page.render(_result(check), now=1000.0)
    assert "<script>" not in page
    assert "<img" not in page
    assert "&lt;script&gt;" in page


def test_the_page_needs_nothing_from_the_network():
    page = status_page.render(_result(_check()), now=1000.0)
    assert "<script" not in page
    assert "http://" not in page and "https://" not in page.replace("https://example.net", "")


def test_only_the_latest_runs_are_drawn():
    samples = [MonitorSample(ts=1000.0 + i, ok=True) for i in range(status_page.BARS + 5)]
    assert status_page.render(_result(_check(samples=samples))).count("<rect") == status_page.BARS


def test_json_has_the_state_and_not_the_samples():
    check = _check(samples=[MonitorSample(ts=1030.0, ok=False)], up=False, since=1030.0)
    state = json.loads(status_page.to_json(_result(check), now=1040.0))
    assert state["ok"] is False and state["time"] == 1040.0
    only = state["checks"][0]
    assert (only["name"], only["state"], only["failures"]) == ("web", "down", 1)
    assert "samples" not in only


def test_cli_option_and_service():
    parser = build_parser()
    args = parser.parse_args(["monitor", "example.net", "--status-page", ":8080"])
    assert args.status_page == ("127.0.0.1", 8080)
    assert service.monitor_arguments(args)[-2:] == ["--status-page", "127.0.0.1:8080"]
    with pytest.raises(SystemExit):
        parser.parse_args(["monitor", "example.net", "--status-page", "nope"])


def _monitor(tmp_path, scrape, **options):
    path = tmp_path / "mon.json"
    path.write_text(json.dumps({"checks": [{"name": "gw", "type": "ping", "host": "h"}]}))
    now = [1_000_000.0]
    seen = []

    def run(entries, workers):
        seen.append(scrape())
        result = PingResult(host="h", ip="192.0.2.1", count=1, rtts=[12.0])
        return [CheckOutcome(e["name"], e["type"], "h", True, "ok", 1.0, result) for e in entries]

    result = monitor_diag.monitor(
        str(path),
        rounds=2,
        quiet=True,
        clock=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        run=run,
        **options,
    )
    return result, seen


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_monitor_serves_the_page_json_and_metrics_on_one_port(tmp_path):
    port = _port()
    base = f"http://127.0.0.1:{port}"

    def scrape():
        return _get(f"{base}/"), _get(f"{base}/status.json"), _get(f"{base}/metrics")

    result, seen = _monitor(tmp_path, scrape, status_page=("127.0.0.1", port))
    assert result.status_url == f"{base}/"
    assert result.metrics_url is None
    (page_status, headers, page), (_, json_headers, state), (_, _, metrics) = seen[-1]
    assert page_status == 200
    assert headers["Content-Type"] == status_page.HTML_TYPE
    assert "All checks up" in page
    assert json_headers["Content-Type"] == status_page.JSON_TYPE
    assert json.loads(state)["checks"][0]["runs"] == 1
    assert "xping_check_runs_total" in metrics


def test_metrics_and_status_page_on_two_ports(tmp_path):
    first, second = _port(), _port()
    if first == second:
        pytest.skip("the system gave the same free port twice")

    def scrape():
        return _get(f"http://127.0.0.1:{first}/"), _get(f"http://127.0.0.1:{second}/")

    result, seen = _monitor(
        tmp_path,
        scrape,
        metrics=("127.0.0.1", first),
        status_page=("127.0.0.1", second),
    )
    assert result.metrics_url == f"http://127.0.0.1:{first}/metrics"
    assert result.status_url == f"http://127.0.0.1:{second}/"
    assert "xping metrics" in seen[-1][0][2]  # the --metrics port keeps its small page
    assert "checks up" in seen[-1][1][2] or "first runs" in seen[-1][1][2]


def test_the_same_address_is_one_server(tmp_path):
    port = _port()
    result, seen = _monitor(
        tmp_path,
        lambda: _get(f"http://127.0.0.1:{port}/metrics")[0],
        metrics=("127.0.0.1", port),
        status_page=("127.0.0.1", port),
    )
    assert seen == [200, 200]
    assert result.metrics_url and result.status_url


def test_a_busy_second_port_stops_the_first_server(tmp_path):
    busy = prometheus.MetricsServer("127.0.0.1", 0, str).start()
    free = _port()
    try:
        with pytest.raises(prometheus.ListenError):
            _monitor(
                tmp_path,
                str,
                metrics=("127.0.0.1", free),
                status_page=busy.address,
            )
        with pytest.raises(urllib.error.URLError):
            _DIRECT.open(f"http://127.0.0.1:{free}/metrics", timeout=2)
    finally:
        busy.stop()


def test_head_and_headers():
    server = prometheus.MetricsServer("127.0.0.1", 0, lambda: "x\n").start()
    try:
        host, port = server.address
        status, headers, body = _get(f"http://{host}:{port}/metrics", "HEAD")
        assert (status, body) == (200, "")
        assert headers["Content-Length"] == "2"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "default-src 'none'" in headers["Content-Security-Policy"]
    finally:
        server.stop()
