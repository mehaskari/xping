"""Compatibility shim — use xping.diagnostics.trace."""

from xping.diagnostics.trace import _raw_trace_hop, _subprocess_trace_live, trace
from xping.models.trace import Hop

__all__ = ["Hop", "trace", "_raw_trace_hop", "_subprocess_trace_live"]
