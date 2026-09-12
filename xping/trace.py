"""Compatibility shim — use xping.diagnostics.trace."""
from xping.models.trace import Hop
from xping.diagnostics.trace import trace, _raw_trace_hop, _subprocess_trace_live

__all__ = ["Hop", "trace", "_raw_trace_hop", "_subprocess_trace_live"]
