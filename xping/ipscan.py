"""Compatibility shim — use xping.diagnostics.ipscan."""

from xping.diagnostics.ipscan import _probe_ip, ipscan
from xping.models.ipscan import IpProbe, IpScanResult

__all__ = ["IpProbe", "IpScanResult", "ipscan", "_probe_ip"]
