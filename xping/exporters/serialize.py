"""Serialize diagnostic dataclasses for export."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

_COMPUTED: dict[str, tuple[str, ...]] = {
    # ping
    "PingResult": (
        "sent",
        "received",
        "lost",
        "loss_pct",
        "min_rtt",
        "max_rtt",
        "avg_rtt",
        "jitter",
        "std_dev",
    ),
    # trace
    "Hop": ("avg_rtt", "label"),
    # tcp
    "TcpResult": (
        "count",
        "successful",
        "failed",
        "success_pct",
        "connect_times",
        "min_connect_ms",
        "max_connect_ms",
        "avg_connect_ms",
    ),
    # portscan
    "PortScanResult": ("scanned", "open_ports", "closed_ports"),
    # sweep
    "HostProbe": ("alive",),
    "SweepResult": ("scanned", "alive_hosts", "alive_count"),
    # ipscan
    "IpScanResult": ("scanned", "alive_hosts", "alive_count"),
    "BundleResult": (),
    "BlocklistCheck": (),
    "BlocklistResult": ("listed", "listed_count", "answered"),
    # rdns
    "RdnsResult": ("resolved",),
    # tls
    "TlsResult": ("days_remaining", "expired", "expiring_soon", "valid"),
    # http
    "HttpResult": ("ok", "redirect_count", "security_missing"),
    "SecurityHeader": (),
    # whois
    "WhoisResult": ("found",),
    # health
    "HealthResult": ("grade",),
    # profile
    "ProfileListResult": ("count",),
    # mtr
    "MtrHop": (
        "sent",
        "received",
        "loss_pct",
        "last",
        "best",
        "worst",
        "avg",
        "stdev",
        "label",
    ),
    "MtrResult": (),
    # mtu
    "MtuResult": ("max_payload",),
    "SpeedResult": ("grade",),
    "ListenEntry": ("address",),
    "ListenResult": ("count",),
    "OsDetectResult": (),
    "NetInterface": ("loopback",),
    "NetResult": (),
    "NtpSample": (),
    "NtpResult": ("offset_ms", "delay_ms", "uncertainty_ms", "synchronized"),
    "UdpAttempt": (),
    "UdpResult": ("state", "replies", "avg_rtt_ms"),
    "CheckOutcome": (),
    "CheckReport": ("passed", "failed", "ok"),
    "WatchSample": (),
    "WatchResult": ("checks", "up_pct", "last_ok", "transitions", "longest_outage_s"),
    "ResolverAnswer": ("answered",),
    "PropagationResult": ("consistent", "distinct_answers", "majority", "matching"),
    "DnsCheckItem": (),
    "DoctorStep": (),
    "DoctorResult": ("ok", "failed", "warnings"),
    "DnsCheckResult": ("grade", "ok_count", "fail_count", "warn_count", "unknown_count"),
}


def _serialize_value(value: Any, *, include_computed: bool) -> Any:
    """Recursively serialize a value from the *original* object graph.

    This must NOT operate on an already-flattened dataclasses.asdict()
    result -- that would convert nested dataclasses into plain dicts
    before their computed (@property) fields could be attached, silently
    dropping fields like MtrHop.loss_pct inside MtrResult.hops, or
    PingResult.avg_rtt inside HealthResult.ping.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return to_dict(value, include_computed=include_computed)
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item, include_computed=include_computed) for item in value]
    if isinstance(value, dict):
        return {
            key: _serialize_value(item, include_computed=include_computed)
            for key, item in value.items()
        }
    return value


def to_dict(obj: Any, *, include_computed: bool = True) -> dict[str, Any]:
    """Convert a dataclass (and nested dataclasses) to a plain dict.

    Walks the real object graph field-by-field so every nested dataclass,
    at any depth, gets its own computed properties applied -- not just the
    top-level object.
    """
    if not is_dataclass(obj) or isinstance(obj, type):
        raise TypeError(f"expected dataclass instance, got {type(obj)!r}")

    data: dict[str, Any] = {}
    for f in fields(obj):
        data[f.name] = _serialize_value(getattr(obj, f.name), include_computed=include_computed)

    if include_computed:
        for name in _COMPUTED.get(type(obj).__name__, ()):
            if hasattr(obj, name):
                data[name] = _serialize_value(getattr(obj, name), include_computed=include_computed)

    return data


def serializable_fields(obj: Any) -> tuple[str, ...]:
    """Return dataclass field names for an instance."""
    if not is_dataclass(obj) or isinstance(obj, type):
        raise TypeError(f"expected dataclass instance, got {type(obj)!r}")
    return tuple(field.name for field in fields(obj))
