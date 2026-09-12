"""Compatibility shim — use xping.diagnostics.ping."""
from xping.models.ping import PingResult
from xping.diagnostics.ping import ping, _icmp_ping, _subprocess_ping_one

__all__ = ["PingResult", "ping", "_icmp_ping", "_subprocess_ping_one"]
