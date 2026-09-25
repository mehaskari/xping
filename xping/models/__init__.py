"""Diagnostic result dataclasses."""

from .bundle import BundleResult
from .dnscheck import DnsCheckItem, DnsCheckResult
from .health import HealthResult
from .http import HttpResult, RedirectHop
from .ipscan import IpProbe, IpScanResult
from .listen import ListenEntry, ListenResult
from .lookup import DnsResult
from .mtr import MtrHop, MtrResult
from .mtu import MtuResult
from .net import NetInterface, NetResult
from .osdetect import OsDetectResult
from .ping import PingResult
from .portscan import PortResult, PortScanResult
from .profile import ProfileEntry, ProfileListResult
from .rdns import RdnsResult
from .speedtest import SpeedResult
from .sweep import HostProbe, SweepResult
from .tcp import TcpAttempt, TcpResult
from .tls import TlsResult
from .trace import Hop
from .whois import WhoisResult

__all__ = [
    "PingResult",
    "Hop",
    "DnsResult",
    "TcpAttempt",
    "TcpResult",
    "PortResult",
    "PortScanResult",
    "HostProbe",
    "SweepResult",
    "IpProbe",
    "IpScanResult",
    "BundleResult",
    "RdnsResult",
    "TlsResult",
    "HttpResult",
    "RedirectHop",
    "WhoisResult",
    "HealthResult",
    "ProfileEntry",
    "ProfileListResult",
    "MtrHop",
    "MtrResult",
    "MtuResult",
    "NetInterface",
    "NetResult",
    "DnsCheckItem",
    "DnsCheckResult",
    "SpeedResult",
    "ListenEntry",
    "ListenResult",
    "OsDetectResult",
]
