"""Diagnostic result dataclasses."""

from .bundle import BundleResult
from .check import CheckOutcome, CheckReport
from .dnscheck import DnsCheckItem, DnsCheckResult
from .doctor import DoctorResult, DoctorStep
from .health import HealthResult
from .http import HttpResult, RedirectHop, SecurityHeader
from .ipscan import IpProbe, IpScanResult
from .listen import ListenEntry, ListenResult
from .lookup import DnsResult
from .mtr import MtrHop, MtrResult
from .mtu import MtuResult
from .net import NetInterface, NetResult
from .ntp import NtpResult, NtpSample
from .osdetect import OsDetectResult
from .ping import PingResult
from .portscan import PortResult, PortScanResult
from .profile import ProfileEntry, ProfileListResult
from .propagation import PropagationResult, ResolverAnswer
from .rdns import RdnsResult
from .speedtest import SpeedResult
from .sweep import HostProbe, SweepResult
from .tcp import TcpAttempt, TcpResult
from .tls import TlsResult
from .trace import Hop
from .udp import UdpAttempt, UdpResult
from .watch import WatchResult, WatchSample
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
    "CheckOutcome",
    "CheckReport",
    "RdnsResult",
    "TlsResult",
    "HttpResult",
    "RedirectHop",
    "SecurityHeader",
    "WhoisResult",
    "HealthResult",
    "ProfileEntry",
    "ProfileListResult",
    "PropagationResult",
    "ResolverAnswer",
    "MtrHop",
    "MtrResult",
    "MtuResult",
    "NetInterface",
    "NetResult",
    "NtpResult",
    "NtpSample",
    "UdpAttempt",
    "UdpResult",
    "DnsCheckItem",
    "DnsCheckResult",
    "DoctorResult",
    "DoctorStep",
    "SpeedResult",
    "ListenEntry",
    "ListenResult",
    "OsDetectResult",
    "WatchResult",
    "WatchSample",
]
