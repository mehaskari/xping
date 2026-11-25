"""Multi-connection speedtest measurement."""

import functools
import http.server
import io
import socketserver
import threading
import time
import urllib.error
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from xping.diagnostics import speedtest as st

RATE = 2_000_000  # bytes/s per stream


class _Throttled(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        size = int(self.path.split("bytes=")[1])
        self.send_response(200)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        chunk, sent, t0 = b"x" * 20000, 0, time.perf_counter()
        while sent < size:
            n = min(len(chunk), size - sent)
            try:
                self.wfile.write(chunk[:n])
            except OSError:
                return
            sent += n
            ahead = sent / RATE - (time.perf_counter() - t0)
            if ahead > 0:
                time.sleep(ahead)


@pytest.fixture
def local_down_url(monkeypatch):
    # talk to the local test server directly, even where a proxy is set
    # (Debian builds point http_proxy at a dead address to block the network)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    srv = Server(("127.0.0.1", 0), _Throttled)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/__down?bytes={{size}}"
    srv.shutdown()


def test_parallel_download_sums_streams(local_down_url):
    with (
        patch.object(st, "_DOWN_URL", local_down_url),
        patch.object(st, "secure_context", lambda: None),
    ):
        single, _, _ = st._measure_download(1, duration=0.6)
        quad, total, err = st._measure_download(4, duration=0.6)
    assert err is None and total > 0
    # Absolute speeds depend on how busy the machine is (a loaded CI runner
    # got half the rate), so check the throttle as a ceiling and that four
    # streams really add up, not the exact numbers.
    stream_mbps = RATE * 8 / 1e6
    assert 0 < single <= stream_mbps * 1.25
    assert quad <= 4 * stream_mbps * 1.25
    assert quad >= 1.8 * single


def test_download_falls_back_to_small_size_on_403():
    urls = []

    def fake_urlopen(req, context=None, timeout=None):
        urls.append(req.full_url)
        if "25000000" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        body = MagicMock()
        body.__enter__.return_value = io.BytesIO(b"x" * 200_000)
        return body

    with patch.object(st.urllib.request, "urlopen", side_effect=fake_urlopen):
        mbps, total, err = st._measure_download(1, duration=5)
    assert urls[0].endswith("25000000") and urls[1].endswith("10000000")
    assert total == 200_000 and err is None


def test_download_reports_error_when_nothing_arrives():
    with patch.object(st.urllib.request, "urlopen", side_effect=OSError("offline")):
        mbps, total, err = st._measure_download(2, duration=1)
    assert mbps is None and total == 0 and "offline" in err


def test_upload_times_only_the_transfer():
    conns = []

    def factory(host, timeout=None, context=None):
        conn = MagicMock()
        conn.getresponse.return_value.read.return_value = b"ok"
        conns.append(conn)
        return conn

    with (
        patch.object(st.http.client, "HTTPSConnection", side_effect=factory),
        patch.object(st, "secure_context", lambda: None),
    ):
        mbps, sent = st._measure_upload(connections=4)
    assert len(conns) == 4 and all(c.connect.called for c in conns)
    assert sent == st._UPLOAD_TOTAL and mbps and mbps > 0


def test_upload_failure_returns_none():
    conn = MagicMock()
    conn.connect.side_effect = OSError("refused")
    with (
        patch.object(st.http.client, "HTTPSConnection", return_value=conn),
        patch.object(st, "secure_context", lambda: None),
    ):
        assert st._measure_upload(connections=2) == (None, 0)


def test_speedtest_records_colo_connections_and_errors():
    with (
        patch.object(st.socket, "gethostbyname", return_value="1.2.3.4"),
        patch.object(st, "_measure_ping", return_value=(12.0, "FRA")),
        patch.object(st, "_measure_download", return_value=(None, 0, "HTTP Error 403")),
        patch.object(st, "_measure_upload", return_value=(40.0, 8_000_000)),
    ):
        r = st.speedtest(connections=3, duration=2, quiet=True)
    assert r.server == "speed.cloudflare.com (FRA)" and r.connections == 3
    assert r.error == "Download failed: HTTP Error 403" and r.upload_mbps == 40.0


def test_cli_flags():
    from xping.cli.parser import build_parser

    args = build_parser().parse_args(["speedtest", "-c", "1", "-d", "3"])
    assert args.connections == 1 and args.duration == 3.0
    with pytest.raises(SystemExit):
        build_parser().parse_args(["speedtest", "-c", "0"])


# ── bufferbloat ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "idle, down, up, bloat, grade",
    [
        (10.0, 12.0, 14.0, 4.0, "A+"),
        (10.0, 35.0, 20.0, 25.0, "A"),
        (10.0, 20.0, 65.0, 55.0, "B"),
        (10.0, 150.0, None, 140.0, "C"),
        (10.0, 300.0, 50.0, 290.0, "D"),
        (10.0, 2000.0, 900.0, 1990.0, "F"),
        (20.0, 18.0, 19.0, 0.0, "A+"),  # loaded faster than idle: no bloat
    ],
)
def test_bufferbloat_grades(idle, down, up, bloat, grade):
    from xping.models.speedtest import SpeedResult

    r = SpeedResult(idle_latency_ms=idle, download_latency_ms=down, upload_latency_ms=up)
    assert r.bufferbloat_ms == pytest.approx(bloat) and r.bufferbloat_grade == grade


def test_bufferbloat_needs_idle_and_a_loaded_sample():
    from xping.models.speedtest import SpeedResult

    assert SpeedResult(idle_latency_ms=10.0).bufferbloat_ms is None
    assert SpeedResult(download_latency_ms=50.0).bufferbloat_grade is None
    d = SpeedResult(download_mbps=50.0).to_dict()
    assert d["bufferbloat_ms"] is None and d["bufferbloat_grade"] is None


class _Conn:
    """Stands in for HTTPSConnection; *fail* makes request() raise."""

    made = 0

    def __init__(self, host, timeout, context, fail=False):
        type(self).made += 1
        self.fail = fail

    def connect(self):
        pass

    def request(self, *args, **kwargs):
        if self.fail:
            raise ConnectionResetError("reset")

    def getresponse(self):
        return io.BytesIO(b"colo=FRA\n")

    def close(self):
        pass


def test_probe_times_round_trips_on_one_connection():
    _Conn.made = 0
    with patch.object(st.http.client, "HTTPSConnection", _Conn):
        probe = st._LatencyProbe()
        assert all(0 <= probe.sample() < 100 for _ in range(3))
    assert _Conn.made == 1  # kept alive, not reconnected per sample


def test_probe_failure_counts_as_timeout_and_reconnects():
    _Conn.made = 0
    conn = functools.partial(_Conn, fail=True)
    with patch.object(st.http.client, "HTTPSConnection", conn):
        probe = st._LatencyProbe(timeout=1.5)
        assert probe.sample() == 1500.0 and probe.sample() == 1500.0
    assert _Conn.made == 2


def test_ping_is_one_round_trip_on_a_warm_connection():
    _Conn.made = 0
    with patch.object(st.http.client, "HTTPSConnection", _Conn):
        ping, colo = st._measure_ping(samples=4)
    assert ping is not None and ping < 100 and colo == "FRA"
    assert _Conn.made == 1  # one handshake, not one per sample


def test_ping_ignores_failed_samples():
    probe = st._LatencyProbe(timeout=2.0)
    with patch.object(probe, "sample", side_effect=[2000.0, 30.0, 25.0]):
        assert st._measure_ping(probe, samples=3) == (25.0, None)
    with patch.object(probe, "sample", return_value=2000.0):
        assert st._measure_ping(probe, samples=2) == (None, None)


def test_idle_is_the_median_and_ignores_timeouts():
    probe = st._LatencyProbe()
    with patch.object(probe, "sample", side_effect=[10.0, 2000.0, 14.0, 12.0]):
        with patch.object(st.time, "sleep"):
            assert probe.idle(probes=4) == 12.0
    with patch.object(probe, "sample", return_value=2000.0), patch.object(st.time, "sleep"):
        assert probe.idle(probes=3) is None


def test_probe_samples_in_the_background_until_the_block_ends():
    probe = st._LatencyProbe()
    with patch.object(probe, "sample", return_value=42.0), patch.object(st, "_PROBE_GAP", 0.01):
        with probe.running():
            time.sleep(0.1)
        n = len(probe.samples)
        time.sleep(0.05)
        assert n >= 2 and len(probe.samples) == n and probe.median == 42.0
        with probe.running():  # a new phase starts with no samples
            pass
    assert len(probe.samples) <= 1


class _FakeProbe:
    def __init__(self):
        self.medians = iter([80.0, 30.0])
        self.idle_calls = 0

    def idle(self):
        self.idle_calls += 1
        return 10.0

    @contextmanager
    def running(self):
        yield self
        self.median = next(self.medians)

    def close(self):
        pass


def _run_speedtest(bufferbloat, download=(100.0, 40_000_000, None), upload=(20.0, 8_000_000)):
    fake = _FakeProbe()
    with (
        patch.object(st.socket, "gethostbyname", return_value="1.2.3.4"),
        patch.object(st, "_measure_ping", return_value=(12.0, "FRA")),
        patch.object(st, "_LatencyProbe", return_value=fake) as cls,
        patch.object(st, "_measure_download", return_value=download),
        patch.object(st, "_measure_upload", return_value=upload),
    ):
        return st.speedtest(quiet=True, bufferbloat=bufferbloat), cls, fake


def test_speedtest_bufferbloat_records_each_phase():
    r, _, fake = _run_speedtest(True)
    assert (r.idle_latency_ms, r.download_latency_ms, r.upload_latency_ms) == (10.0, 80.0, 30.0)
    assert r.bufferbloat_ms == 70.0 and r.bufferbloat_grade == "C"
    assert fake.idle_calls == 1


def test_speedtest_without_bufferbloat_does_not_probe():
    r, _, fake = _run_speedtest(False)
    assert fake.idle_calls == 0 and next(fake.medians) == 80.0  # never ran a phase
    assert r.idle_latency_ms is None and r.bufferbloat_ms is None


def test_failed_transfers_do_not_report_loaded_latency():
    r, _, _ = _run_speedtest(True, download=(None, 0, "boom"), upload=(None, 0))
    assert r.download_latency_ms is None and r.upload_latency_ms is None
    assert r.bufferbloat_ms is None


def test_bufferbloat_cli_flags_and_threshold():
    from xping.cli.parser import build_parser
    from xping.models.speedtest import SpeedResult
    from xping.verdict import evaluate

    assert build_parser().parse_args(["speedtest", "-b"]).bufferbloat
    args = build_parser().parse_args(["speedtest", "--max-bloat", "30"])
    assert args.max_bloat == 30.0 and not args.bufferbloat
    bloated = SpeedResult(download_mbps=50.0, idle_latency_ms=10.0, download_latency_ms=90.0)
    [failure] = evaluate(bloated, args)
    assert failure.threshold and failure.message == (
        "latency rose 80 ms under load, over --max-bloat 30"
    )
    [failure] = evaluate(SpeedResult(download_mbps=50.0), args)
    assert failure.message == "bufferbloat could not be measured"
    fine = SpeedResult(download_mbps=50.0, idle_latency_ms=10.0, download_latency_ms=25.0)
    assert evaluate(fine, args) == []


def test_max_bloat_turns_bufferbloat_on():
    from xping.cli.commands import cmd_speedtest
    from xping.cli.parser import build_parser
    from xping.models.speedtest import SpeedResult

    for argv, expected in (
        (["speedtest", "-q"], False),
        (["speedtest", "-q", "-b"], True),
        (["speedtest", "-q", "--max-bloat", "50"], True),
    ):
        with patch("xping.cli.commands.speedtest", return_value=SpeedResult()) as run:
            cmd_speedtest(build_parser().parse_args(argv))
        assert run.call_args.kwargs["bufferbloat"] is expected


def test_check_file_bufferbloat_and_max_bloat():
    from xping.diagnostics import check
    from xping.models.speedtest import SpeedResult

    with patch("xping.diagnostics.speedtest.speedtest", return_value=SpeedResult()) as run:
        check._run_speedtest({})
        check._run_speedtest({"bufferbloat": True})
        check._run_speedtest({"max_bloat": 30})
    assert [c.kwargs["bufferbloat"] for c in run.call_args_list] == [False, True, True]
    assert "max_bloat" in check.THRESHOLD_KEYS


def test_diff_compares_bufferbloat():
    from xping.diagnostics.diff import METRICS

    assert any(m.path == "bufferbloat_ms" for m in METRICS["speedtest"])
