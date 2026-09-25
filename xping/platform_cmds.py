"""Compatibility shim — use xping.diagnostics.platform_cmds."""

from xping.diagnostics.platform_cmds import (
    mtu_probe_command,
    mtu_probe_succeeded,
    parse_ping_rtt,
    parse_trace_line,
    ping_command,
    system_name,
    trace_command,
    trace_tool,
)

__all__ = [
    "mtu_probe_command",
    "mtu_probe_succeeded",
    "parse_ping_rtt",
    "parse_trace_line",
    "ping_command",
    "system_name",
    "trace_command",
    "trace_tool",
]
