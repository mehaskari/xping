"""Compatibility shim — use xping.diagnostics.portscan."""
from xping.models.portscan import PortResult, PortScanResult
from xping.diagnostics.portscan import parse_ports, portscan, scan_port

__all__ = ["PortResult", "PortScanResult", "parse_ports", "portscan", "scan_port"]
