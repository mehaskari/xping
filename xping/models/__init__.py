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
    "DnsCheckItem",
    "DnsCheckResult",
    "SpeedResult",
    "ListenEntry",
    "ListenResult",
]
