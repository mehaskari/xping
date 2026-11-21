"""Private storage, the monitor's HTTP server limits, the webhook from the
environment, and CSV cells a spreadsheet would run."""

import http.client
import socket
import sys
import time
from unittest.mock import patch

import pytest

from xping import paths
from xping.exporters import prometheus as prom
from xping.exporters.csv import _csv_cell

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")


# ── ~/.xping is owner-only ───────────────────────────────────────────────────


@posix_only
def test_private_dir_creates_and_tightens_up_to_dot_xping(tmp_path):
    root = tmp_path / ".xping"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    history = paths.private_dir(root / "history" / "ping")
    assert history.is_dir()
    for directory in (root, root / "history", history):
        assert directory.stat().st_mode & 0o777 == 0o700


@posix_only
def test_private_dir_leaves_directories_above_dot_xping_alone(tmp_path):
    tmp_path.chmod(0o755)
    paths.private_dir(tmp_path / ".xping")
    assert tmp_path.stat().st_mode & 0o777 == 0o755


@posix_only
def test_private_dir_outside_dot_xping_only_touches_itself(tmp_path):
    outer = tmp_path / "data"
    outer.mkdir(mode=0o755)
    outer.chmod(0o755)
    paths.private_dir(outer / "hist")
    assert (outer / "hist").stat().st_mode & 0o777 == 0o700
    assert outer.stat().st_mode & 0o777 == 0o755


@posix_only
def test_history_record_uses_a_private_directory(tmp_path):
    from xping.diagnostics import history
    from xping.models.ping import PingResult

    base = tmp_path / ".xping" / "history"
    result = PingResult(host="h", ip="192.0.2.1", count=1)
    path = history.record("ping", "h", result, True, base=base)
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert (tmp_path / ".xping").stat().st_mode & 0o777 == 0o700


# ── the monitor's HTTP server ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "header, name",
    [
        ("localhost:9101", "localhost"),
        ("127.0.0.1", "127.0.0.1"),
        ("[::1]:8080", "::1"),
        ("Evil.Example:80", "evil.example"),
        ("::1", "::1"),
    ],
)
def test_host_header_name(header, name):
    assert prom._host_header_name(header) == name


def test_is_loopback():
    assert prom.is_loopback("127.0.0.1") and prom.is_loopback("::1")
    assert prom.is_loopback("localhost") and prom.is_loopback("127.0.0.53")
    assert not prom.is_loopback("0.0.0.0") and not prom.is_loopback("192.0.2.1")


@pytest.fixture
def server():
    srv = prom.MetricsServer("127.0.0.1", 0, lambda: "m 1\n").start()
    yield srv
    srv.stop()


def _get(port: int, host: str | None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest("GET", "/metrics", skip_host=True)
    if host is not None:
        conn.putheader("Host", host)
    conn.endheaders()
    resp = conn.getresponse()
    return resp.status, resp.read()


def test_loopback_server_refuses_foreign_host_headers(server):
    port = server.address[1]
    assert _get(port, f"127.0.0.1:{port}") == (200, b"m 1\n")
    assert _get(port, f"localhost:{port}")[0] == 200
    assert _get(port, f"app.localhost:{port}")[0] == 200
    assert _get(port, None)[0] == 200  # HTTP/1.0 style, no Host
    assert _get(port, f"rebind.attacker.example:{port}")[0] == 403


def test_public_server_accepts_any_host_header():
    srv = prom.MetricsServer("0.0.0.0", 0, lambda: "m 1\n").start()
    try:
        assert _get(srv.address[1], "monitor.example.net")[0] == 200
    finally:
        srv.stop()


def test_idle_connection_is_dropped(server):
    with patch.object(prom._Handler, "timeout", 0.3):
        sock = socket.create_connection(server.address, timeout=5)
        try:
            time.sleep(0.8)
            assert sock.recv(1) == b""  # the server closed it
        finally:
            sock.close()


def test_connections_beyond_the_limit_are_dropped(server):
    with patch.object(prom, "MAX_CONNECTIONS", 2):
        srv = prom.MetricsServer("127.0.0.1", 0, lambda: "m 1\n").start()
    idle = []
    try:
        idle = [socket.create_connection(srv.address, timeout=5) for _ in range(2)]
        time.sleep(0.2)  # both are being served (waiting for a request)
        extra = socket.create_connection(srv.address, timeout=5)
        try:
            assert extra.recv(1) == b""  # dropped at once instead of queued
        finally:
            extra.close()
        for sock in idle:
            sock.close()
        idle = []
        time.sleep(0.3)  # slots freed
        assert _get(srv.address[1], "localhost")[0] == 200
    finally:
        for sock in idle:
            sock.close()
        srv.stop()


# ── XPING_WEBHOOK ────────────────────────────────────────────────────────────


def _parse(argv):
    import argparse
    import importlib

    from xping.cli.parser import build_parser

    main_mod = importlib.import_module("xping.cli.main")

    parser = build_parser()
    args = parser.parse_args(argv)
    main_mod._webhook_from_environment(parser, args)
    return args, argparse


def test_webhook_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("XPING_WEBHOOK", "https://ntfy.sh/topic")
    args, _ = _parse(["monitor", "1.1.1.1"])
    assert args.webhook == "https://ntfy.sh/topic"
    args, _ = _parse(["monitor", "1.1.1.1", "--webhook", "https://h.test/x"])
    assert args.webhook == "https://h.test/x"  # the option wins
    args, _ = _parse(["lookup", "example.net"])  # no alerts in this command
    assert not hasattr(args, "webhook")


def test_invalid_environment_webhook_is_a_usage_error(monkeypatch):
    monkeypatch.setenv("XPING_WEBHOOK", "file:///etc/passwd")
    with pytest.raises(SystemExit) as exc:
        _parse(["monitor", "1.1.1.1"])
    assert exc.value.code == 2


# ── CSV cells a spreadsheet would run ────────────────────────────────────────


@pytest.mark.parametrize(
    "value, cell",
    [
        ('=HYPERLINK("https://x","y")', '\'=HYPERLINK("https://x","y")'),
        ("+1+1", "'+1+1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("-2+3", "'-2+3"),
        ("\tx", "'"),  # control characters are stripped by cell(); "'" stays harmless
        ("-12.5", "-12.5"),
        ("v=spf1 -all", "v=spf1 -all"),
        (-3.0, "-3"),
        (None, ""),
    ],
)
def test_csv_cells_are_never_formulas(value, cell):
    out = _csv_cell(value)
    if value == "\tx":
        assert not out.startswith(("=", "+", "-", "@", "\t"))
    else:
        assert out == cell


def test_csv_export_of_a_txt_record():
    from xping.exporters.csv import export_csv
    from xping.models.lookup import DnsResult

    text = export_csv(DnsResult(host="evil.example", txt=["=cmd|' /C calc'!A0"]))
    assert "=cmd" not in text.replace("'=cmd", "")
