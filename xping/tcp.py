"""Compatibility shim — use xping.diagnostics.tcp."""

from xping.diagnostics.tcp import _connect_once, _resolve, tcp
from xping.models.tcp import TcpAttempt, TcpResult

__all__ = ["TcpAttempt", "TcpResult", "tcp", "_connect_once", "_resolve"]
