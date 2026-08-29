"""Serialize diagnostic dataclasses for export."""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from typing import Any


_COMPUTED: dict[type, tuple[str, ...]] = {
    # ping
    "PingResult": (
        "sent", "received", "lost", "loss_pct",
        "min_rtt", "max_rtt", "avg_rtt", "jitter", "std_dev",
    ),
    # trace
    "Hop": ("avg_rtt", "label"),
    # tcp
    "TcpResult": (
        "count", "successful", "failed", "success_pct",
        "connect_times", "min_connect_ms", "max_connect_ms", "avg_connect_ms",
    ),
    # portscan
    "PortScanResult": ("scanned", "open_ports", "closed_ports"),
    # sweep
    "HostProbe": ("alive",),
    "SweepResult": ("scanned", "alive_hosts", "alive_count"),
    # ipscan
    "IpScanResult": ("scanned", "alive_hosts", "alive_count"),
    "BundleResult": (),
    # rdns
    "RdnsResult": ("resolved",),
    # tls
    "TlsResult": ("days_remaining", "expired", "expiring_soon", "valid"),
    # http
    "HttpResult": ("ok", "redirect_count"),
    # whois
    "WhoisResult": ("found",),
    # health
    "HealthResult": ("grade",),
    # profile
    "ProfileListResult": ("count",),
    # mtr
    "MtrHop": (
        "sent", "received", "loss_pct", "last", "best", "worst", "avg",
        "stdev", "label",
    ),
    "MtrResult": (),
    # mtu
    "MtuResult": ("max_payload",),
    "SpeedResult": ("grade",),
    "ListenEntry": ("address",),
    "ListenResult": ("count",),
    "DnsCheckItem": (),
    "DnsCheckResult": ("grade", "ok_count", "fail_count", "warn_count"),
}


def _nested_to_dict(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        # Use to_dict (with computed props) if available, else fall back
        if hasattr(value, 'to_dict'):
            return value.to_dict()
        return to_dict(value)
    if isinstance(value, list):
        return [_nested_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _nested_to_dict(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_nested_to_dict(item) for item in value]
    return value


def to_dict(obj: Any, *, include_computed: bool = True) -> dict[str, Any]:
    """Convert a dataclass (and nested dataclasses) to a plain dict."""
    if not is_dataclass(obj) or isinstance(obj, type):
        raise TypeError(f"expected dataclass instance, got {type(obj)!r}")

    data = asdict(obj)
    data = _nested_to_dict(data)

    if include_computed:
        computed = _COMPUTED.get(type(obj).__name__, ())
        for name in computed:
            if hasattr(obj, name):
                data[name] = _nested_to_dict(getattr(obj, name))

    return data


def serializable_fields(obj: Any) -> tuple[str, ...]:
    """Return dataclass field names for an instance."""
    if not is_dataclass(obj) or isinstance(obj, type):
        raise TypeError(f"expected dataclass instance, got {type(obj)!r}")
    return tuple(field.name for field in fields(obj))
