"""Multi-connection speedtest measurement."""

import http.server
import io
import socketserver
import threading
import time
import urllib.error
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
def local_down_url():
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
    assert single == pytest.approx(RATE * 8 / 1e6, rel=0.25)
    assert quad == pytest.approx(4 * RATE * 8 / 1e6, rel=0.25)


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
