"""Compatibility shim — use xping.diagnostics.ping."""

from xping.diagnostics.ping import _icmp_ping, _subprocess_ping_one, ping
from xping.models.ping import PingResult

__all__ = ["PingResult", "ping", "_icmp_ping", "_subprocess_ping_one"]
