"""Compatibility shim — use xping.diagnostics.sweep."""
from xping.models.sweep import HostProbe, SweepResult
from xping.diagnostics.sweep import parse_targets, sweep, _probe_host

__all__ = ["HostProbe", "SweepResult", "parse_targets", "sweep", "_probe_host"]
