"""Compatibility shim — use xping.diagnostics.ipscan."""
from xping.models.ipscan import IpProbe, IpScanResult
from xping.diagnostics.ipscan import ipscan, _probe_ip

__all__ = ["IpProbe", "IpScanResult", "ipscan", "_probe_ip"]
