"""
xping test suite.
Run with: python -m pytest tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import socket
import subprocess
from unittest.mock import patch, MagicMock


# ── render module ─────────────────────────────────────────────────────────────

def test_render_imports():
    from xping import render
    assert hasattr(render, "banner")
    assert hasattr(render, "section_header")
    assert hasattr(render, "kv")
    assert hasattr(render, "latency_color")
    assert hasattr(render, "spark_bar")


def test_banner_returns_string():
    from xping.render import banner
    b = banner()
    assert isinstance(b, str)
    assert len(b) > 50   # banner has substantial content


def test_latency_color_no_crash():
    from xping.render import supports_color, latency_color
    # patch colour off so output is plain
    with patch("xping.render.COLOR", False):
        assert "10.00 ms" in latency_color(10.0)
        assert "timeout"  in latency_color(-1.0)


def test_spark_bar_empty():
    from xping.render import spark_bar
    assert spark_bar([]) == ""


def test_spark_bar_values():
    from xping.render import spark_bar
    with patch("xping.render.COLOR", False):
        result = spark_bar([10.0, 50.0, 200.0, -1.0])
        assert isinstance(result, str)


def test_print_table_no_crash():
    from xping.render import print_table
    import io
    with patch("xping.render.COLOR", False):
        buf = io.StringIO()
        with patch("builtins.print", side_effect=lambda *a, **k: buf.write(" ".join(str(x) for x in a) + "\n")):
            print_table(["Col A", "Col B"], [["val1", "val2"], ["val3", "val4"]])
    out = buf.getvalue()
    assert "Col A" in out
    assert "val1" in out


# ── ping module ───────────────────────────────────────────────────────────────

def test_ping_bad_host():
    from xping.ping import ping
    result = ping("this.host.does.not.exist.invalid", count=1, quiet=True)
    assert result.resolved is False
    assert result.ip == "?"


def test_ping_result_properties():
    from xping.ping import PingResult
    r = PingResult(host="test", ip="1.2.3.4", count=4,
                   rtts=[10.0, 20.0, -1.0, 15.0])
    assert r.sent == 4
    assert r.received == 3
    assert r.lost == 1
    assert abs(r.loss_pct - 25.0) < 0.1
    assert r.min_rtt == 10.0
    assert r.max_rtt == 20.0
    assert abs(r.avg_rtt - 15.0) < 0.1


def test_ping_all_timeout():
    from xping.ping import PingResult
    r = PingResult(host="test", ip="1.2.3.4", count=3,
                   rtts=[-1.0, -1.0, -1.0])
    assert r.received == 0
    assert r.loss_pct == 100.0
    assert r.avg_rtt == -1


# ── lookup module ─────────────────────────────────────────────────────────────

def test_lookup_parse_dig_a():
    from xping.lookup import _parse_dig_a
    sample = "github.com.\t\t60\tIN\tA\t140.82.121.4\n"
    ips, ttl = _parse_dig_a(sample)
    assert "140.82.121.4" in ips
    assert ttl == 60


def test_lookup_parse_dig_mx():
    from xping.lookup import _parse_dig_mx
    sample = (
        "github.com.\t3600\tIN\tMX\t1 aspmx.l.google.com.\n"
        "github.com.\t3600\tIN\tMX\t5 alt1.aspmx.l.google.com.\n"
    )
    records = _parse_dig_mx(sample)
    assert len(records) == 2
    assert records[0][0] == 1
    assert "google" in records[0][1]


def test_lookup_parse_dig_ns():
    from xping.lookup import _parse_dig_ns
    sample = "github.com.\t172800\tIN\tNS\tns1.p16.dynect.net.\n"
    ns = _parse_dig_ns(sample)
    assert len(ns) == 1
    assert "dynect" in ns[0]


def test_lookup_parse_dig_txt():
    from xping.lookup import _parse_dig_txt
    sample = 'github.com.\t3600\tIN\tTXT\t"v=spf1 ip4:192.30.252.0/22 include:_netblocks.google.com ~all"\n'
    txts = _parse_dig_txt(sample)
    assert any("spf1" in t for t in txts)


def test_lookup_bad_host():
    from xping.lookup import lookup
    with patch("socket.gethostbyname", side_effect=socket.gaierror):
        with patch("xping.diagnostics.lookup._dig_query", return_value=None):
            with patch("xping.diagnostics.lookup._socket_resolve", return_value=([], [])):
                with patch("builtins.print"):  # suppress output
                    result = lookup("this.host.totally.invalid")
    assert result.error is not None


# ── tcp module ────────────────────────────────────────────────────────────────

def test_tcp_result_properties():
    from xping.tcp import TcpAttempt, TcpResult
    result = TcpResult(
        host="example.com",
        port=443,
        ip="93.184.216.34",
        attempts=[
            TcpAttempt(seq=1, ok=True, elapsed_ms=20.0),
            TcpAttempt(seq=2, ok=False, elapsed_ms=100.0, error="timeout"),
            TcpAttempt(seq=3, ok=True, elapsed_ms=10.0),
        ],
    )
    assert result.count == 3
    assert result.successful == 2
    assert result.failed == 1
    assert abs(result.success_pct - 66.6) < 0.2
    assert result.min_connect_ms == 10.0
    assert result.max_connect_ms == 20.0
    assert result.avg_connect_ms == 15.0


def test_tcp_bad_host():
    from xping.tcp import tcp
    with patch("xping.diagnostics.tcp._resolve", side_effect=socket.gaierror("not found")):
        with patch("builtins.print"):
            result = tcp("this.host.totally.invalid", 443, quiet=True)
    assert result.resolved is False
    assert result.ip == "?"
    assert result.error is not None


def test_tcp_success_quiet():
    from xping.tcp import TcpAttempt, tcp
    with patch("xping.diagnostics.tcp._resolve", return_value="127.0.0.1"):
        with patch("xping.diagnostics.tcp._connect_once", return_value=TcpAttempt(seq=1, ok=True, elapsed_ms=5.0)):
            result = tcp("localhost", 80, count=1, quiet=True)
    assert result.resolved is True
    assert result.successful == 1
    assert result.avg_connect_ms == 5.0


# ── portscan module ───────────────────────────────────────────────────────────

def test_parse_ports_accepts_lists_and_ranges():
    from xping.portscan import parse_ports
    assert parse_ports("22,80,443,8000-8002") == [22, 80, 443, 8000, 8001, 8002]


def test_parse_ports_rejects_invalid_port():
    from xping.portscan import parse_ports
    try:
        parse_ports("0,80")
    except ValueError as exc:
        assert "between 1 and 65535" in str(exc)
    else:
        raise AssertionError("invalid port was accepted")


def test_portscan_quiet_success():
    from xping.portscan import PortResult, portscan
    with patch("socket.gethostbyname", return_value="127.0.0.1"):
        with patch("xping.diagnostics.portscan.scan_port", side_effect=[
            PortResult(port=22, open=False, elapsed_ms=1.0),
            PortResult(port=443, open=True, elapsed_ms=2.0, service="https"),
        ]):
            result = portscan("localhost", [22, 443], quiet=True)
    assert result.resolved is True
    assert result.scanned == 2
    assert [item.port for item in result.open_ports] == [443]


def test_portscan_bad_host():
    from xping.portscan import portscan
    with patch("socket.gethostbyname", side_effect=socket.gaierror("not found")):
        result = portscan("bad.invalid", [80], quiet=True)
    assert result.resolved is False
    assert result.error is not None


# ── sweep module ──────────────────────────────────────────────────────────────

def test_parse_targets_cidr_and_range():
    from xping.sweep import parse_targets
    assert parse_targets("192.0.2.0/30") == ["192.0.2.1", "192.0.2.2"]
    assert parse_targets("192.0.2.10-192.0.2.12") == [
        "192.0.2.10",
        "192.0.2.11",
        "192.0.2.12",
    ]


def test_parse_targets_limit():
    from xping.sweep import parse_targets
    try:
        parse_targets("192.0.2.0/24", limit=4)
    except ValueError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("oversized target range was accepted")


def test_sweep_quiet_success():
    from xping.sweep import HostProbe, sweep
    with patch("xping.diagnostics.sweep.parse_targets", return_value=["192.0.2.1", "192.0.2.2"]):
        with patch("xping.diagnostics.sweep._probe_host", side_effect=[
            HostProbe(ip="192.0.2.1", open_ports=[22], elapsed_ms=4.0),
            HostProbe(ip="192.0.2.2", open_ports=[], elapsed_ms=4.0),
        ]):
            result = sweep("192.0.2.0/30", [22], quiet=True)
    assert result.scanned == 2
    assert result.alive_count == 1
    assert result.alive_hosts[0].ip == "192.0.2.1"


# ── ipscan module ─────────────────────────────────────────────────────────────

def test_ipscan_parse_ping_rtt():
    from xping.platform_cmds import parse_ping_rtt
    assert parse_ping_rtt("64 bytes from 127.0.0.1: time=0.123 ms") == 0.123
    assert parse_ping_rtt("Reply from 127.0.0.1: time<1ms") == 1.0
    assert parse_ping_rtt("no timing") == -1.0


def test_ipscan_probe_alive():
    from xping.ipscan import _probe_ip
    completed = subprocess.CompletedProcess(
        args=["ping"],
        returncode=0,
        stdout="64 bytes from 127.0.0.1: time=0.5 ms",
        stderr="",
    )
    with patch("xping.diagnostics.ipscan.subprocess.run", return_value=completed):
        probe = _probe_ip("127.0.0.1", timeout=1.0)
    assert probe.alive is True
    assert probe.rtt_ms == 0.5


def test_ipscan_quiet_success():
    from xping.ipscan import IpProbe, ipscan
    with patch("xping.diagnostics.ipscan.parse_targets", return_value=["192.0.2.1", "192.0.2.2"]):
        with patch("xping.diagnostics.ipscan.require", return_value=True):
            with patch("xping.diagnostics.ipscan._probe_ip", side_effect=[
                IpProbe(ip="192.0.2.1", alive=True, elapsed_ms=2.0, rtt_ms=1.0),
                IpProbe(ip="192.0.2.2", alive=False, elapsed_ms=2.0, error="no reply"),
            ]):
                result = ipscan("192.0.2.0/30", quiet=True)
    assert result.scanned == 2
    assert result.alive_count == 1
    assert result.alive_hosts[0].ip == "192.0.2.1"


def test_ipscan_missing_ping():
    from xping.ipscan import ipscan
    with patch("xping.diagnostics.ipscan.parse_targets", return_value=["192.0.2.1"]):
        with patch("xping.diagnostics.ipscan.require", return_value=False):
            result = ipscan("192.0.2.1/32", quiet=True)
    assert result.error == "'ping' not found"


# ── trace module ──────────────────────────────────────────────────────────────

def test_hop_avg_rtt():
    from xping.trace import Hop
    hop = Hop(ttl=1, host="router.local", ip="10.0.0.1",
              rtts=[10.0, 20.0, -1.0])
    assert hop.avg_rtt == 15.0
    assert hop.label == "router.local (10.0.0.1)"


def test_hop_timeout_label():
    from xping.trace import Hop
    hop = Hop(ttl=5, host=None, ip=None, rtts=[-1.0, -1.0], timeout=True)
    assert hop.label == "* * *"
    assert hop.avg_rtt == -1.0


def test_trace_unresolvable_host():
    from xping.trace import trace
    with patch("socket.gethostbyname", side_effect=socket.gaierror):
        with patch("xping.diagnostics.trace.resolve_error") as mock_error:
            result = trace("bad.invalid")
    assert result == []
    mock_error.assert_called_once()


def test_subprocess_trace_live_parses_hops():
    from xping.trace import Hop, _subprocess_trace_live
    lines = [
        " 1  10.0.0.1 (10.0.0.1)  1.234 ms  2.345 ms  3.456 ms\n",
        " 2  192.0.2.1 (192.0.2.1)  10.1 ms  11.2 ms  12.3 ms\n",
    ]

    class FakeStdout:
        def __iter__(self):
            return iter(lines)

    class FakeProc:
        stdout = FakeStdout()

        def wait(self):
            return 0

    seen = []
    with patch("xping.diagnostics.trace.subprocess.Popen", return_value=FakeProc()):
        hops = _subprocess_trace_live("example.com", 30, 3, on_hop=seen.append)

    assert len(hops) == 2
    assert hops[0].ttl == 1
    assert hops[0].ip == "10.0.0.1"
    assert len(seen) == 2
    assert isinstance(hops[1], Hop)


def test_raw_trace_hop_no_permission():
    from xping.trace import _raw_trace_hop
    with patch("xping.diagnostics.trace.socket.socket", side_effect=PermissionError):
        assert _raw_trace_hop("1.1.1.1", 1, 33434) is None


# ── deps module ───────────────────────────────────────────────────────────────

def test_install_cmd_debian_ping():
    from xping.deps import install_cmd
    with patch("xping.diagnostics.deps.get_distro", return_value="debian"):
        cmd = install_cmd("ping")
    assert "apt install" in cmd
    assert "iputils-ping" in cmd


def test_is_available_true():
    from xping.deps import is_available
    with patch("xping.diagnostics.deps.shutil.which", return_value="/usr/bin/ping"):
        assert is_available("ping") is True


def test_require_missing_binary():
    from xping.deps import require
    with patch("xping.diagnostics.deps.is_available", return_value=False):
        with patch("xping.diagnostics.deps.install_cmd", return_value="sudo apt install ping"):
            with patch("xping.diagnostics.deps.missing_tool") as mock_error:
                ok = require("ping", "testing")
    assert ok is False
    mock_error.assert_called_once()


def test_check_all_returns_expected_keys():
    from xping.deps import check_all
    with patch("xping.diagnostics.deps.is_available", return_value=True):
        tools = check_all()
    assert set(tools) == {"ping", "traceroute", "dig"}
    assert all(tools.values())


def test_get_distro_from_os_release(monkeypatch):
    from xping.diagnostics import deps
    import io

    deps._DISTRO = None
    monkeypatch.setattr(deps.platform, "system", lambda: "Linux")

    def fake_open(path, *args, **kwargs):
        if str(path) == "/etc/os-release":
            return io.StringIO("ID=ubuntu\nNAME=Ubuntu\n")
        raise FileNotFoundError(path)

    monkeypatch.setattr("builtins.open", fake_open)
    assert deps.get_distro() == "debian"


# ── render views ──────────────────────────────────────────────────────────────

def test_ping_view_renders_summary(capsys):
    from xping.ping import PingResult
    from xping.render.views import ping as ping_view
    result = PingResult(host="test", ip="1.1.1.1", count=2, rtts=[10.0, 20.0])
    with patch("xping.render.COLOR", False):
        ping_view.print_summary(result)
    out = capsys.readouterr().out
    assert "test" in out
    assert "1.1.1.1" in out


def test_trace_view_renders_hop(capsys):
    from xping.trace import Hop
    from xping.render.views import trace as trace_view
    hop = Hop(ttl=3, host="gw.local", ip="10.0.0.1", rtts=[12.0, 14.0, 16.0])
    with patch("xping.render.COLOR", False):
        trace_view.print_hop(hop)
    assert "10.0.0.1" in capsys.readouterr().out


def test_lookup_view_renders_result(capsys):
    from xping.lookup import DnsResult
    from xping.render.views import lookup as lookup_view
    result = DnsResult(
        host="example.com",
        ipv4=["93.184.216.34"],
        ttl=60,
        reverse={"93.184.216.34": "example.com"},
    )
    with patch("xping.render.COLOR", False):
        lookup_view.print_result(result)
    assert "example.com" in capsys.readouterr().out


def test_tcp_view_renders_summary(capsys):
    from xping.tcp import TcpAttempt, TcpResult
    from xping.render.views import tcp as tcp_view
    result = TcpResult(
        host="example.com",
        port=443,
        ip="93.184.216.34",
        attempts=[TcpAttempt(seq=1, ok=True, elapsed_ms=5.0)],
    )
    with patch("xping.render.COLOR", False):
        tcp_view.print_summary(result)
    assert "443" in capsys.readouterr().out


def test_portscan_view_renders_open_port(capsys):
    from xping.portscan import PortResult
    from xping.render.views import portscan as portscan_view
    item = PortResult(port=443, open=True, elapsed_ms=3.0, service="https")
    with patch("xping.render.COLOR", False):
        portscan_view.print_port_result(item)
    assert "443" in capsys.readouterr().out


def test_sweep_view_renders_alive_host(capsys):
    from xping.sweep import HostProbe
    from xping.render.views import sweep as sweep_view
    probe = HostProbe(ip="192.0.2.1", open_ports=[22, 80], elapsed_ms=4.0)
    with patch("xping.render.COLOR", False):
        sweep_view.print_probe(probe)
    assert "192.0.2.1" in capsys.readouterr().out


def test_ipscan_view_renders_alive_host(capsys):
    from xping.ipscan import IpProbe
    from xping.render.views import ipscan as ipscan_view
    probe = IpProbe(ip="192.0.2.1", alive=True, elapsed_ms=2.0, rtt_ms=1.0)
    with patch("xping.render.COLOR", False):
        ipscan_view.print_probe(probe)
    assert "192.0.2.1" in capsys.readouterr().out


def test_trace_reaches_destination(capsys):
    from xping.trace import Hop, trace
    hops = [
        Hop(ttl=1, host="gw", ip="10.0.0.1", rtts=[1.0, 2.0, 3.0]),
        Hop(ttl=2, host=None, ip="1.1.1.1", rtts=[10.0, 11.0, 12.0]),
    ]
    with patch("socket.gethostbyname", return_value="1.1.1.1"):
        with patch("xping.diagnostics.trace._raw_trace_hop", side_effect=hops):
            with patch("sys.stdout.isatty", return_value=False):
                with patch("xping.render.COLOR", False):
                    result = trace("1.1.1.1", max_hops=5)
    assert len(result) == 2
    assert "TRACEROUTE" in capsys.readouterr().out


def test_print_deps_status(capsys):
    from xping.deps import print_deps_status
    with patch("xping.diagnostics.deps.check_all", return_value={"ping": True, "traceroute": False, "dig": True}):
        with patch("xping.diagnostics.deps.get_distro", return_value="debian"):
            with patch("xping.render.COLOR", False):
                print_deps_status()
    out = capsys.readouterr().out
    assert "DEPENDENCY CHECK" in out
    assert "traceroute" in out


# ── render errors ─────────────────────────────────────────────────────────────

def test_render_error_api():
    from xping.render import error
    import io
    buf = io.StringIO()
    with patch("xping.render.COLOR", False):
        error("something failed", hint="try again", file=buf)
    out = buf.getvalue()
    assert "something failed" in out
    assert "try again" in out


def test_render_spinner():
    from xping.render import Spinner
    spinner = Spinner("working")
    spinner.start()
    spinner.stop()


# ── platform integration ──────────────────────────────────────────────────────

def test_subprocess_ping_one_parses_output():
    from xping.ping import _subprocess_ping_one
    completed = subprocess.CompletedProcess(
        args=["ping"], returncode=0,
        stdout="64 bytes from 1.1.1.1: time=7.5 ms", stderr="",
    )
    with patch("xping.diagnostics.ping.subprocess.run", return_value=completed):
        assert _subprocess_ping_one("1.1.1.1", 1.0) == 7.5


def test_icmp_ping_timeout():
    from xping.ping import _icmp_ping
    class FakeSock:
        def __init__(self, *args, **kwargs):
            pass
        def settimeout(self, _value):
            pass
        def sendto(self, *_args, **_kwargs):
            pass
        def recvfrom(self, _size):
            raise AssertionError("should not be reached")
        def close(self):
            pass
    with patch("xping.diagnostics.ping.socket.socket", return_value=FakeSock()):
        with patch("xping.diagnostics.ping.socket.gethostbyname", return_value="1.1.1.1"):
            with patch("xping.diagnostics.ping.select.select", return_value=([], [], [])):
                assert _icmp_ping("1.1.1.1", 1, timeout=0.1) == -1.0


def test_ping_quiet_subprocess_fallback():
    from xping.ping import ping
    with patch("socket.gethostbyname", return_value="1.1.1.1"):
        with patch("xping.diagnostics.ping._icmp_ping", return_value=None):
            with patch("xping.diagnostics.ping.is_available", return_value=True):
                with patch("xping.diagnostics.ping._subprocess_ping_one", return_value=12.0):
                    result = ping("1.1.1.1", count=1, quiet=True)
    assert result.received == 1
    assert result.avg_rtt == 12.0


def test_lookup_with_dig_path():
    from xping.lookup import lookup
    dig_outputs = {
        "A": "example.com.\t60\tIN\tA\t93.184.216.34\n",
        "AAAA": "",
        "CNAME": "",
        "MX": "example.com.\t3600\tIN\tMX\t10 mail.example.com.\n",
        "NS": "example.com.\t3600\tIN\tNS\tns.example.com.\n",
        "TXT": 'example.com.\t3600\tIN\tTXT\t"v=spf1 include:example.com ~all"\n',
    }
    with patch("xping.diagnostics.lookup._dig_query", side_effect=lambda _host, rtype: dig_outputs.get(rtype)):
        with patch("socket.gethostbyaddr", return_value=("example.com", [], [])):
            with patch("xping.render.COLOR", False):
                result = lookup("example.com", full=True)
    assert "93.184.216.34" in result.ipv4
    assert result.mx
    assert result.ns
    assert result.txt


def test_lookup_socket_fallback():
    from xping.lookup import lookup
    with patch("xping.diagnostics.lookup._dig_query", return_value=None):
        with patch("xping.diagnostics.lookup._socket_resolve", return_value=(["93.184.216.34"], [])):
            with patch("socket.gethostbyaddr", side_effect=socket.herror):
                with patch("xping.render.COLOR", False):
                    result = lookup("example.com")
    assert result.ipv4 == ["93.184.216.34"]


def test_portscan_renders_closed_port(capsys):
    from xping.portscan import PortResult
    from xping.render.views import portscan as portscan_view
    item = PortResult(port=22, open=False, elapsed_ms=1.0, error="timeout")
    with patch("xping.render.COLOR", False):
        portscan_view.print_port_result(item)
    assert "22" in capsys.readouterr().out


def test_portscan_scan_port_timeout():
    from xping.portscan import scan_port
    with patch("xping.diagnostics.portscan.socket.create_connection", side_effect=TimeoutError):
        result = scan_port("127.0.0.1", 22, timeout=0.1)
    assert result.open is False
    assert result.error == "timeout"


def test_sweep_view_renders_silent_host(capsys):
    from xping.sweep import HostProbe
    from xping.render.views import sweep as sweep_view
    probe = HostProbe(ip="192.0.2.2", open_ports=[], elapsed_ms=1.0)
    with patch("xping.render.COLOR", False):
        sweep_view.print_probe(probe)
    assert "192.0.2.2" in capsys.readouterr().out


def test_ipscan_view_renders_silent_host(capsys):
    from xping.ipscan import IpProbe
    from xping.render.views import ipscan as ipscan_view
    probe = IpProbe(ip="192.0.2.2", alive=False, elapsed_ms=1.0, error="no reply")
    with patch("xping.render.COLOR", False):
        ipscan_view.print_probe(probe)
    out = capsys.readouterr().out
    assert "192.0.2.2" in out
    assert "no reply" in out


def test_trace_subprocess_fallback(capsys):
    from xping.trace import Hop, trace
    hops = [Hop(ttl=1, host="gw", ip="10.0.0.1", rtts=[1.0, 2.0, 3.0])]
    with patch("socket.gethostbyname", return_value="1.1.1.1"):
        with patch("xping.diagnostics.trace._raw_trace_hop", return_value=None):
            with patch("xping.diagnostics.trace.is_available", return_value=True):
                with patch("xping.diagnostics.trace._subprocess_trace_live", return_value=hops) as mock_live:
                    with patch("sys.stdout.isatty", return_value=False):
                        with patch("xping.render.COLOR", False):
                            result = trace("1.1.1.1", max_hops=3, probes=2)
    assert result == hops
    mock_live.assert_called_once()


def test_trace_view_timeout_hop(capsys):
    from xping.trace import Hop
    from xping.render.views import trace as trace_view
    hop = Hop(ttl=4, host=None, ip=None, rtts=[-1.0, -1.0], timeout=True)
    with patch("xping.render.COLOR", False):
        trace_view.print_hop(hop)
    assert "no response" in capsys.readouterr().out


def test_ping_view_print_line(capsys):
    from xping.render.views import ping as ping_view
    with patch("xping.render.COLOR", False):
        ping_view.print_line(1, "1.1.1.1", 12.5, 3)
        ping_view.print_line(2, "1.1.1.1", -1.0, 3)
    out = capsys.readouterr().out
    assert "12.5" in out or "timeout" in out


def test_tcp_view_print_failed_line(capsys):
    from xping.tcp import TcpAttempt
    from xping.render.views import tcp as tcp_view
    attempt = TcpAttempt(seq=1, ok=False, elapsed_ms=2.0, error="timeout")
    with patch("xping.render.COLOR", False):
        tcp_view.print_line(attempt, 1)
    assert "timeout" in capsys.readouterr().out


def test_render_progress_line(capsys):
    from xping.render import progress_line
    with patch("xping.render.COLOR", False):
        progress_line("working", done=True)
    assert "working" in capsys.readouterr().out


def test_render_warn_api(capsys):
    from xping.render import warn
    with patch("xping.render.COLOR", False):
        warn("heads up", hint="more detail")
    out = capsys.readouterr().out
    assert "heads up" in out
    assert "more detail" in out


def test_render_resolve_error(capsys):
    from xping.render import resolve_error
    import io
    buf = io.StringIO()
    with patch("xping.render.COLOR", False):
        resolve_error("bad.host", socket.gaierror("failed"))
    # resolve_error writes to stderr by default through error()


def test_deps_detects_darwin(monkeypatch):
    from xping.diagnostics import deps
    deps._DISTRO = None
    monkeypatch.setattr(deps.platform, "system", lambda: "Darwin")
    assert deps.get_distro() == "darwin"


def test_deps_detects_windows(monkeypatch):
    from xping.diagnostics import deps
    deps._DISTRO = None
    monkeypatch.setattr(deps.platform, "system", lambda: "Windows")
    assert deps.get_distro() == "windows"


def test_deps_traceroute_available_via_tracert():
    from xping.deps import is_available
    with patch("xping.diagnostics.platform_cmds.trace_tool", return_value="tracert"):
        assert is_available("traceroute") is True


def test_get_distro_fedora(monkeypatch):
    from xping.diagnostics import deps
    import io
    deps._DISTRO = None
    monkeypatch.setattr(deps.platform, "system", lambda: "Linux")

    def fake_open(path, *args, **kwargs):
        if str(path) == "/etc/os-release":
            return io.StringIO("ID=fedora\n")
        raise FileNotFoundError(path)

    monkeypatch.setattr("builtins.open", fake_open)
    assert deps.get_distro() == "rhel"


def test_portscan_view_summary(capsys):
    from xping.portscan import PortResult, PortScanResult
    from xping.render.views import portscan as portscan_view
    result = PortScanResult(
        host="host", ip="1.1.1.1", ports=[443],
        results=[PortResult(port=443, open=True, elapsed_ms=2.0, service="https")],
    )
    with patch("xping.render.COLOR", False):
        portscan_view.print_summary(result)
    assert "443" in capsys.readouterr().out


def test_sweep_view_summary(capsys):
    from xping.sweep import HostProbe, SweepResult
    from xping.render.views import sweep as sweep_view
    result = SweepResult(
        target="192.0.2.0/30", ports=[80],
        hosts=[HostProbe(ip="192.0.2.1", open_ports=[80], elapsed_ms=3.0)],
    )
    with patch("xping.render.COLOR", False):
        sweep_view.print_summary(result)
    assert "192.0.2.1" in capsys.readouterr().out


def test_ipscan_view_summary(capsys):
    from xping.ipscan import IpProbe, IpScanResult
    from xping.render.views import ipscan as ipscan_view
    result = IpScanResult(
        target="192.0.2.0/30",
        probes=[IpProbe(ip="192.0.2.1", alive=True, elapsed_ms=1.0, rtt_ms=0.5)],
    )
    with patch("xping.render.COLOR", False):
        ipscan_view.print_summary(result)
    assert "192.0.2.1" in capsys.readouterr().out


def test_portscan_interactive():
    from xping.portscan import PortResult, portscan
    with patch("socket.gethostbyname", return_value="127.0.0.1"):
        with patch("xping.diagnostics.portscan.scan_port", return_value=PortResult(port=80, open=True, elapsed_ms=1.0, service="http")):
            with patch("xping.render.COLOR", False):
                with patch("builtins.print"):
                    result = portscan("localhost", [80], quiet=False)
    assert result.open_ports[0].port == 80


def test_sweep_interactive():
    from xping.sweep import HostProbe, sweep
    with patch("xping.diagnostics.sweep.parse_targets", return_value=["192.0.2.1"]):
        with patch("xping.diagnostics.sweep._probe_host", return_value=HostProbe(ip="192.0.2.1", open_ports=[80], elapsed_ms=2.0)):
            with patch("xping.render.COLOR", False):
                with patch("builtins.print"):
                    result = sweep("192.0.2.0/30", [80], quiet=False)
    assert result.alive_count == 1


def test_ipscan_interactive():
    from xping.ipscan import IpProbe, ipscan
    with patch("xping.diagnostics.ipscan.parse_targets", return_value=["192.0.2.1"]):
        with patch("xping.diagnostics.ipscan.require", return_value=True):
            with patch("xping.diagnostics.ipscan._probe_ip", return_value=IpProbe(ip="192.0.2.1", alive=True, elapsed_ms=1.0, rtt_ms=0.5)):
                with patch("xping.render.COLOR", False):
                    with patch("builtins.print"):
                        result = ipscan("192.0.2.0/30", quiet=False)
    assert result.alive_count == 1


def test_tcp_interactive():
    from xping.tcp import TcpAttempt, tcp
    with patch("xping.diagnostics.tcp._resolve", return_value="127.0.0.1"):
        with patch("xping.diagnostics.tcp._connect_once", return_value=TcpAttempt(seq=1, ok=True, elapsed_ms=3.0)):
            with patch("xping.render.COLOR", False):
                with patch("builtins.print"):
                    result = tcp("localhost", 80, count=1, quiet=False)
    assert result.successful == 1


def test_raw_trace_hop_success():
    from xping.trace import _raw_trace_hop
    recv_sock = MagicMock()
    send_sock = MagicMock()

    class SockFactory:
        def __init__(self):
            self.calls = 0
        def __call__(self, *args, **kwargs):
            self.calls += 1
            return recv_sock if self.calls % 2 == 1 else send_sock

    recv_sock.recvfrom.return_value = (b"\x00" * 20 + bytes([11]), ("10.0.0.1", 0))
    factory = SockFactory()
    with patch("xping.diagnostics.trace.socket.socket", side_effect=factory):
        with patch("xping.diagnostics.trace.select.select", return_value=([recv_sock], [], [])):
            with patch("xping.diagnostics.trace._reverse", return_value="gw.local"):
                hop = _raw_trace_hop("1.1.1.1", 1, 33434, timeout=1.0, probes=1)
    assert hop is not None
    assert hop.ip == "10.0.0.1"


def test_lookup_parse_cname_and_aaaa():
    from xping.lookup import _parse_dig_aaaa, _parse_dig_cname
    aaaa = "example.com.\t60\tIN\tAAAA\t2001:db8::1\n"
    assert _parse_dig_aaaa(aaaa) == ["2001:db8::1"]
    cname = "www.example.com.\t60\tIN\tCNAME\texample.com.\n"
    assert _parse_dig_cname(cname) == "example.com"


def test_print_deps_status_raw_socket_denied(capsys):
    from xping.deps import print_deps_status
    with patch("xping.diagnostics.deps.check_all", return_value={"ping": True, "traceroute": True, "dig": True}):
        with patch("xping.diagnostics.deps.get_distro", return_value="debian"):
            with patch("xping.render.COLOR", False):
                with patch("socket.socket", side_effect=PermissionError):
                    print_deps_status()
    assert "Raw sockets" in capsys.readouterr().out


def test_render_resolve_error_with_exc(capsys):
    from xping.render import missing_tool, resolve_error
    with patch("xping.render.COLOR", False):
        resolve_error("bad.host", ValueError("lookup failed"))
        missing_tool("dig", "DNS lookup", "brew install bind")
    err = capsys.readouterr().err
    assert "bad.host" in err
    assert "dig" in err
    from xping.ping import PingResult
    from xping.serialize import serializable_fields
    result = PingResult(host="t", ip="1.1.1.1", count=1)
    assert serializable_fields(result) == ("host", "ip", "count", "rtts", "resolved")


def test_ping_interactive_renders(capsys):
    from xping.ping import ping
    with patch("socket.gethostbyname", return_value="1.1.1.1"):
        with patch("xping.diagnostics.ping._icmp_ping", return_value=5.0):
            with patch("sys.stdout.isatty", return_value=False):
                with patch("xping.render.COLOR", False):
                    result = ping("1.1.1.1", count=1, quiet=False)
    out = capsys.readouterr().out
    assert result.received == 1
    assert "1.1.1.1" in out


def test_trace_view_summary_unreachable(capsys):
    from xping.trace import Hop
    from xping.render.views import trace as trace_view
    hops = [Hop(ttl=1, host="gw", ip="10.0.0.1", rtts=[1.0], timeout=False)]
    with patch("xping.render.COLOR", False):
        trace_view.print_summary(hops, "example.com", "93.184.216.34")
    assert "NOT REACHED" in capsys.readouterr().out


def test_lookup_view_ipv6_and_txt(capsys):
    from xping.lookup import DnsResult
    from xping.render.views import lookup as lookup_view
    result = DnsResult(
        host="example.com",
        ipv6=["2001:db8::1"],
        txt=["v=spf1 include:example.com ~all"],
        reverse={"2001:db8::1": "example.com"},
    )
    with patch("xping.render.COLOR", False):
        lookup_view.print_result(result, full=True)
    out = capsys.readouterr().out
    assert "2001:db8::1" in out
    assert "spf1" in out


# ── CLI entry point ───────────────────────────────────────────────────────────

def test_cli_version():
    from xping.__main__ import build_parser
    parser = build_parser()
    args = parser.parse_args(["-V"])
    assert args.version is True


def test_cli_ping_args():
    from xping.__main__ import build_parser
    parser = build_parser()
    args = parser.parse_args(["ping", "google.com", "-c", "3", "-i", "0.1"])
    assert args.command == "ping"
    assert args.host == "google.com"
    assert args.count == 3
    assert args.interval == 0.1


def test_cli_trace_args():
    from xping.__main__ import build_parser
    parser = build_parser()
    args = parser.parse_args(["trace", "8.8.8.8", "--max-hops", "15"])
    assert args.command == "trace"
    assert args.max_hops == 15


def test_cli_lookup_args():
    from xping.__main__ import build_parser
    parser = build_parser()
    args = parser.parse_args(["lookup", "github.com", "--full"])
    assert args.command == "lookup"
    assert args.full is True


def test_cli_tcp_args():
    from xping.__main__ import build_parser
    parser = build_parser()
    args = parser.parse_args(["tcp", "example.com", "443", "-c", "4", "-t", "1"])
    assert args.command == "tcp"
    assert args.host == "example.com"
    assert args.port == 443
    assert args.count == 4
    assert args.timeout == 1


def test_cli_tcp_rejects_invalid_port():
    from xping.__main__ import build_parser
    parser = build_parser()
    with patch("sys.stderr"):
        try:
            parser.parse_args(["tcp", "example.com", "70000"])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("invalid TCP port was accepted")


def test_cli_portscan_args():
    from xping.__main__ import build_parser
    parser = build_parser()
    args = parser.parse_args(["portscan", "example.com", "--ports", "22,80,443", "-w", "8"])
    assert args.command == "portscan"
    assert args.host == "example.com"
    assert args.ports == [22, 80, 443]
    assert args.workers == 8


def test_cli_sweep_args():
    from xping.__main__ import build_parser
    parser = build_parser()
    args = parser.parse_args(["sweep", "192.168.1.0/30", "--ports", "22,80"])
    assert args.command == "sweep"
    assert args.target == "192.168.1.0/30"
    assert args.ports == [22, 80]


def test_cli_ipscan_args():
    from xping.__main__ import build_parser
    parser = build_parser()
    args = parser.parse_args(["ipscan", "192.168.1.0/30", "-t", "0.2", "-w", "4"])
    assert args.command == "ipscan"
    assert args.target == "192.168.1.0/30"
    assert args.timeout == 0.2
    assert args.workers == 4
