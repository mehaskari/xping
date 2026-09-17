"""Compatibility shim — use xping.diagnostics.sweep."""

from xping.diagnostics.sweep import _probe_host, parse_targets, sweep
from xping.models.sweep import HostProbe, SweepResult

__all__ = ["HostProbe", "SweepResult", "parse_targets", "sweep", "_probe_host"]
