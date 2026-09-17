"""Compatibility shim — use xping.diagnostics.portscan."""

from xping.diagnostics.portscan import parse_ports, portscan, scan_port
from xping.models.portscan import PortResult, PortScanResult

__all__ = ["PortResult", "PortScanResult", "parse_ports", "portscan", "scan_port"]
