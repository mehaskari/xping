"""Compatibility shim — use xping.diagnostics.tcp."""
from xping.models.tcp import TcpAttempt, TcpResult
from xping.diagnostics.tcp import tcp, _connect_once, _resolve

__all__ = ["TcpAttempt", "TcpResult", "tcp", "_connect_once", "_resolve"]
