"""Diagnostic result dataclasses."""

from .ping import PingResult
from .trace import Hop
from .lookup import DnsResult
from .tcp import TcpAttempt, TcpResult
from .portscan import PortResult, PortScanResult
from .sweep import HostProbe, SweepResult
from .ipscan import IpProbe, IpScanResult
from .bundle import BundleResult
from .rdns import RdnsResult
from .tls import TlsResult
from .http import HttpResult, RedirectHop
from .whois import WhoisResult
from .health import HealthResult
from .profile import ProfileEntry, ProfileListResult
from .mtr import MtrHop, MtrResult
from .mtu import MtuResult
from .dnscheck import DnsCheckItem, DnsCheckResult
from .speedtest import SpeedResult
from .listen import ListenEntry, ListenResult

__all__ = [
    "BundleResult",
    "DnsCheckItem",
    "DnsCheckResult",
    "DnsResult",
    "HealthResult",
    "Hop",
    "HostProbe",
    "HttpResult",
    "IpProbe",
    "IpScanResult",
    "ListenEntry",
    "ListenResult",
    "MtrHop",
    "MtrResult",
    "MtuResult",
    "PingResult",
    "PortResult",
    "PortScanResult",
    "ProfileEntry",
    "ProfileListResult",
    "RdnsResult",
    "RedirectHop",
    "SpeedResult",
    "SweepResult",
    "TcpAttempt",
    "TcpResult",
    "TlsResult",
    "WhoisResult",
]
