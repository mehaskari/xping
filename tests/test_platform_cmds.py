"""Tests for cross-platform ping and traceroute command helpers."""

from unittest.mock import patch


def test_ping_command_linux():
    from xping.platform_cmds import ping_command
    with patch("xping.diagnostics.platform_cmds.system_name", return_value="linux"):
        assert ping_command("1.1.1.1", 2.0) == ["ping", "-c", "1", "-W", "2", "1.1.1.1"]


def test_ping_command_darwin():
    from xping.platform_cmds import ping_command
    with patch("xping.diagnostics.platform_cmds.system_name", return_value="darwin"):
        cmd = ping_command("1.1.1.1", 1.5)
    assert cmd == ["ping", "-c", "1", "-W", "1500", "1.1.1.1"]


def test_ping_command_windows():
    from xping.platform_cmds import ping_command
    with patch("xping.diagnostics.platform_cmds.system_name", return_value="windows"):
        cmd = ping_command("1.1.1.1", 2.0)
    assert cmd == ["ping", "-n", "1", "-w", "2000", "1.1.1.1"]


def test_parse_ping_rtt_variants():
    from xping.platform_cmds import parse_ping_rtt
    assert parse_ping_rtt("64 bytes from 1.1.1.1: time=12.34 ms") == 12.34
    assert parse_ping_rtt("Reply from 127.0.0.1: time<1ms") == 1.0
    assert parse_ping_rtt("no timing here") == -1.0


def test_trace_command_unix():
    from xping.platform_cmds import trace_command
    with patch("xping.diagnostics.platform_cmds.trace_tool", return_value="traceroute"):
        cmd = trace_command("example.com", 20, 2)
    assert cmd == ["traceroute", "-m", "20", "-q", "2", "-w", "2", "example.com"]


def test_trace_command_passes_timeout():
    from xping.platform_cmds import trace_command
    with patch("xping.diagnostics.platform_cmds.trace_tool", return_value="traceroute"):
        assert trace_command("h", 5, 1, timeout=4.0)[-3:] == ["-w", "4", "h"]
    with patch("xping.diagnostics.platform_cmds.trace_tool", return_value="tracert"):
        assert trace_command("h", 5, 1, timeout=0.5)[-3:] == ["-w", "500", "h"]


def test_trace_command_windows():
    from xping.platform_cmds import trace_command
    with patch("xping.diagnostics.platform_cmds.trace_tool", return_value="tracert"):
        cmd = trace_command("example.com", 15, 3)
    assert cmd == ["tracert", "-h", "15", "-w", "2000", "example.com"]


def test_parse_traceroute_line():
    from xping.platform_cmds import parse_trace_line
    line = " 1  gw.local (10.0.0.1)  1.234 ms  2.345 ms  3.456 ms"
    with patch("xping.diagnostics.platform_cmds.system_name", return_value="linux"):
        parsed = parse_trace_line(line)
    assert parsed == (1, [1.234, 2.345, 3.456], "10.0.0.1", "gw.local")


def test_parse_tracert_line():
    from xping.platform_cmds import parse_trace_line
    line = "  1    <1 ms    <1 ms    <1 ms  192.168.1.1"
    with patch("xping.diagnostics.platform_cmds.system_name", return_value="windows"):
        parsed = parse_trace_line(line)
    assert parsed is not None
    ttl, rtts, ip, _hostname = parsed
    assert ttl == 1
    assert ip == "192.168.1.1"
    assert len(rtts) == 3


def test_parse_trace_line_ignores_header():
    from xping.platform_cmds import parse_trace_line
    with patch("xping.diagnostics.platform_cmds.system_name", return_value="linux"):
        assert parse_trace_line("traceroute to example.com") is None


def test_trace_tool_prefers_traceroute():
    from xping.platform_cmds import trace_tool
    with patch("xping.diagnostics.platform_cmds.shutil.which", side_effect=lambda name: name == "traceroute"):
        assert trace_tool() == "traceroute"


def test_trace_tool_falls_back_to_tracert():
    from xping.platform_cmds import trace_tool
    with patch("xping.diagnostics.platform_cmds.shutil.which", side_effect=lambda name: name == "tracert"):
        assert trace_tool() == "tracert"
