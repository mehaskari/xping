"""
xping.diagnostics.diff — compare two runs of the same check.

Save a baseline with --json, run again later, and see what changed:

    xping ping example.com --json > before.json
    ...
    xping ping example.com --json | xping diff before.json -

The kind of result (ping, trace, http, …) is recognised from the JSON's
shape. For each kind a few meaningful numbers are compared (with the
direction that counts as better), plus status changes (dnscheck checks,
doctor steps, check-file outcomes, blocklists) and set changes (DNS
records, the route of a traceroute). Anything else falls back to
comparing every numeric field.

--max-regression PCT turns it into a gate: exit 1 when a metric got worse
by more than PCT percent or a status got worse.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass

from xping.models.diff import DiffResult, MetricChange

LOWER, HIGHER, NEUTRAL = "lower", "higher", "neutral"
NOISE_PCT = 3.0


@dataclass(frozen=True)
class Metric:
    label: str
    path: str
    better: str = LOWER
    unit: str = "ms"


# Changes smaller than this are noise, never a regression
_MIN_ABS = {"ms": 1.0, "%": 1.0, "Mbit/s": 1.0, "dBm": 2.0, "dB": 2.0, "days": 1.0, "": 0.5}

_STATUS_RANK = {
    "ok": 0,
    "clean": 0,
    "pass": 0,
    "info": 1,
    "skip": 1,
    "policy": 2,
    "warn": 2,
    "unknown": 3,
    "refused": 3,
    "error": 4,
    "fail": 5,
    "listed": 5,
}

METRICS: dict[str, tuple[Metric, ...]] = {
    "ping": (
        Metric("Average RTT", "avg_rtt"),
        Metric("Min RTT", "min_rtt"),
        Metric("Max RTT", "max_rtt"),
        Metric("Jitter", "jitter"),
        Metric("Packet loss", "loss_pct", unit="%"),
    ),
    "tcp": (
        Metric("Average connect", "avg_connect_ms"),
        Metric("Success rate", "success_pct", HIGHER, "%"),
    ),
    "udp": (Metric("Average reply", "avg_rtt_ms"),),
    "http": (
        Metric("Total time", "total_ms"),
        Metric("DNS lookup", "dns_ms"),
        Metric("TCP connect", "tcp_ms"),
        Metric("TLS handshake", "tls_ms"),
        Metric("Server response", "ttfb_ms"),
        Metric("Download", "transfer_ms"),
        Metric("Body size", "body_bytes", NEUTRAL, "bytes"),
    ),
    "tls": (Metric("Days remaining", "days_remaining", HIGHER, "days"),),
    "health": (
        Metric("Health score", "score", HIGHER, ""),
        Metric("DNS resolve", "dns_resolve_ms"),
        Metric("Average RTT", "ping.avg_rtt"),
        Metric("Jitter", "ping.jitter"),
        Metric("Packet loss", "ping.loss_pct", unit="%"),
    ),
    "dnscheck": (Metric("DNS score", "score", HIGHER, ""),),
    "speedtest": (
        Metric("Download", "download_mbps", HIGHER, "Mbit/s"),
        Metric("Upload", "upload_mbps", HIGHER, "Mbit/s"),
        Metric("Latency", "ping_ms"),
    ),
    "ntp": (
        Metric("Clock offset (abs)", "abs:offset_ms"),
        Metric("Round-trip delay", "delay_ms"),
    ),
    "wifi": (
        Metric("Signal", "current.signal_dbm", HIGHER, "dBm"),
        Metric("SNR", "current.snr_db", HIGHER, "dB"),
        Metric("Link rate", "tx_rate_mbps", HIGHER, "Mbit/s"),
        Metric("Networks on channel", "same_channel", LOWER, ""),
    ),
    "trace": (
        Metric("Hops", "len:", NEUTRAL, ""),
        Metric("Final hop RTT", "last:avg_rtt"),
    ),
    "mtr": (
        Metric("Destination loss", "dest:loss_pct", unit="%"),
        Metric("Destination avg RTT", "dest:avg"),
        Metric("Hops", "len:hops", NEUTRAL, ""),
    ),
    "check": (
        Metric("Checks passed", "passed", HIGHER, ""),
        Metric("Checks failed", "failed", LOWER, ""),
    ),
    "blocklist": (Metric("Listings", "listed_count", LOWER, ""),),
}

# kind -> [(label, list path, key field(s), value field)]
STATUSES = {
    "dnscheck": [("check", "checks", ("name",), "status")],
    "doctor": [("step", "steps", ("name",), "status")],
    "check": [("check", "outcomes", ("name",), "ok")],
    "blocklist": [("list", "checks", ("list_name", "subject"), "status")],
}
# kind -> [(label, path)] — lists compared as sets
SETS = {
    "lookup": [("A", "ipv4"), ("AAAA", "ipv6"), ("NS", "ns"), ("MX", "mx"), ("TXT", "txt")],
    "http": [("missing security header", "security_missing")],
    "tls": [("SAN", "san")],
}
# kind -> [(label, path)] — single values reported when they change
SCALARS = {
    "http": [
        ("status", "status_code"),
        ("final URL", "final_url"),
        ("HTTP version", "http_version"),
    ],
    "tls": [("issuer", "issuer"), ("expires", "not_after"), ("protocol", "protocol")],
    "lookup": [("CNAME", "cname")],
    "udp": [("state", "state")],
    "ntp": [("stratum", "stratum"), ("reference", "reference")],
    "wifi": [("channel", "current.channel"), ("band", "current.band")],
    "health": [("grade", "grade")],
    "speedtest": [("grade", "grade")],
    "doctor": [("diagnosis", "diagnosis")],
}


def detect(data) -> str:
    """Which command produced this JSON."""
    if isinstance(data, list):
        return "trace" if all(isinstance(h, dict) and "ttl" in h for h in data) else "generic"
    if not isinstance(data, dict):
        return "generic"
    keys = set(data)
    rules = (
        ("check", {"outcomes"}),
        ("doctor", {"steps", "diagnosis"}),
        ("dnscheck", {"checks", "score", "domain"}),
        ("blocklist", {"checks", "kind", "target"}),
        ("health", {"score", "grade", "host"}),
        ("speedtest", {"download_mbps"}),
        ("mtr", {"hops", "dest_ip"}),
        ("http", {"status_code", "url"}),
        ("tls", {"days_remaining"}),
        ("ntp", {"offset_ms", "server"}),
        ("udp", {"probe", "attempts"}),
        ("tcp", {"attempts", "avg_connect_ms"}),
        ("ping", {"rtts", "loss_pct"}),
        ("lookup", {"ipv4", "ipv6", "ns"}),
        ("propagation", {"answers", "rtype"}),
        ("wifi", {"current", "nearby"}),
    )
    return next((kind for kind, needed in rules if needed <= keys), "generic")


def _get(data, path: str):
    """Value at a dotted *path*; special prefixes len:, last:, dest:, abs:."""
    if path.startswith("len:"):
        target = _get(data, path[4:]) if path[4:] else data
        return len(target) if isinstance(target, list) else None
    if path.startswith("last:"):
        hops = [h for h in data if isinstance(h, dict) and not h.get("timeout")]
        return hops[-1].get(path[5:]) if hops else None
    if path.startswith("dest:"):
        dest = data.get("dest_ip")
        hop = next((h for h in reversed(data.get("hops", [])) if h.get("ip") == dest), None)
        return hop.get(path[5:]) if hop else None
    if path.startswith("abs:"):
        value = _get(data, path[4:])
        return abs(value) if isinstance(value, int | float) else None
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return None if value == -1 else float(value)  # -1 means "no data" in xping results


def compare_metric(metric: Metric, before, after) -> MetricChange | None:
    b, a = _number(_get(before, metric.path)), _number(_get(after, metric.path))
    if b is None and a is None:
        return None
    change = MetricChange(metric.label, b, a, metric.unit, metric.better)
    if b is None or a is None:
        change.verdict = "changed"
        return change
    change.change_pct = (a - b) / abs(b) * 100 if b else (0.0 if a == b else None)
    # noise: a tiny absolute change, or under 3 % of the old value
    small = abs(a - b) < _MIN_ABS.get(metric.unit, 0.0) or (
        change.change_pct is not None and abs(change.change_pct) < NOISE_PCT
    )
    if a == b or small or metric.better == NEUTRAL:
        change.verdict = "same" if a == b or small else "changed"
    else:
        improved = a < b if metric.better == LOWER else a > b
        change.verdict = "better" if improved else "worse"
    return change


def _generic_metrics(before, after) -> list[MetricChange]:
    """Every numeric top-level field that exists on both sides."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    changes = []
    for key in before:
        if key in after and _number(before[key]) is not None and _number(after[key]) is not None:
            change = compare_metric(Metric(key, key, NEUTRAL, ""), before, after)
            if change and change.verdict != "same":
                changes.append(change)
    return changes


def _status_changes(kind: str, before, after, result: DiffResult) -> None:
    for label, path, key_fields, value_field in STATUSES.get(kind, []):
        old = _index(before, path, key_fields, value_field)
        new = _index(after, path, key_fields, value_field)
        for key in sorted(set(old) | set(new)):
            o, n = old.get(key), new.get(key)
            if o == n:
                continue
            os_, ns_ = _status_text(o), _status_text(n)
            line = f"{label} {key}: {os_} → {ns_}"
            result.changes.append(line)
            if key in old and key in new and _rank(n) > _rank(o):
                result.regressions.append(line)


def _index(data, path: str, key_fields: tuple[str, ...], value_field: str) -> dict:
    return {
        " / ".join(str(item.get(k)) for k in key_fields): item.get(value_field)
        for item in data.get(path, []) or []
        if isinstance(item, dict)
    }


def _status_text(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "pass" if value else "fail"
    return str(value)


def _rank(value) -> int:
    if isinstance(value, bool):
        return 0 if value else 5
    return _STATUS_RANK.get(str(value), 3)


def _as_items(values) -> list[str]:
    items = []
    for value in values or []:
        items.append(" ".join(map(str, value)) if isinstance(value, list | tuple) else str(value))
    return items


def _set_changes(kind: str, before, after, result: DiffResult) -> None:
    for label, path in SETS.get(kind, []):
        old, new = set(_as_items(_get(before, path))), set(_as_items(_get(after, path)))
        for item in sorted(new - old):
            result.changes.append(f"+ {label} {item}")
        for item in sorted(old - new):
            result.changes.append(f"− {label} {item}")
    for label, path in SCALARS.get(kind, []):
        o, n = _get(before, path), _get(after, path)
        if o != n:
            result.changes.append(
                f"{label}: {o if o is not None else '—'} → {n if n is not None else '—'}"
            )


def _route_changes(kind: str, before, after, result: DiffResult) -> None:
    """Traceroute / mtr: which hops now go through a different router."""
    if kind == "trace":
        old_hops, new_hops = before, after
    elif kind == "mtr":
        old_hops, new_hops = before.get("hops", []), after.get("hops", [])
    else:
        return
    old = {h.get("ttl"): h.get("ip") for h in old_hops if isinstance(h, dict)}
    new = {h.get("ttl"): h.get("ip") for h in new_hops if isinstance(h, dict)}
    changed = [
        ttl
        for ttl in sorted(set(old) | set(new), key=lambda t: t or 0)
        if old.get(ttl) and new.get(ttl) and old[ttl] != new[ttl]
    ]
    for ttl in changed:
        result.changes.append(f"hop {ttl}: {old[ttl]} → {new[ttl]}")
    if changed:
        result.changes.insert(0, f"route changed from hop {changed[0]} on")


def _propagation_changes(before, after, result: DiffResult) -> None:
    old = {a.get("resolver"): a.get("records") for a in before.get("answers", [])}
    new = {a.get("resolver"): a.get("records") for a in after.get("answers", [])}
    for resolver in sorted(set(old) | set(new), key=str):
        if old.get(resolver) != new.get(resolver):
            o = ", ".join(old.get(resolver) or []) or "—"
            n = ", ".join(new.get(resolver) or []) or "—"
            result.changes.append(f"{resolver}: {o} → {n}")


def compare(before, after, max_regression: float | None = None) -> DiffResult:
    kind, other = detect(before), detect(after)
    result = DiffResult(kind=kind)
    if kind != other:
        result.error = f"cannot compare a {kind} result with a {other} result"
        return result
    specs = METRICS.get(kind)
    metrics = (
        [compare_metric(m, before, after) for m in specs]
        if specs
        else _generic_metrics(before, after)
    )
    result.metrics = [m for m in metrics if m is not None]
    _status_changes(kind, before, after, result)
    _set_changes(kind, before, after, result)
    _route_changes(kind, before, after, result)
    if kind == "propagation":
        _propagation_changes(before, after, result)
    for m in result.metrics:
        if m.verdict == "worse":
            pct = f"{m.change_pct:+.0f}%" if m.change_pct is not None else "worse"
            line = f"{m.label} {pct}"
            if max_regression is None or m.change_pct is None or abs(m.change_pct) > max_regression:
                result.regressions.append(line)
    result.max_regression = max_regression
    return result


# ── files ─────────────────────────────────────────────────────────────────────


def _load(path: str) -> tuple[object, str]:
    """(parsed JSON, display label) for a file path or "-" (stdin)."""
    if path == "-":
        return json.loads(sys.stdin.read()), "stdin"
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
    return data, f"{path}  ({stamp})"


def diff(
    before_path: str,
    after_path: str,
    max_regression: float | None = None,
    quiet: bool = False,
) -> DiffResult:
    """Raises ValueError (bad JSON / unreadable file) for the CLI to report."""
    if before_path == "-" and after_path == "-":
        raise ValueError("only one side can be read from stdin ('-')")
    try:
        before, before_label = _load(before_path)
        after, after_label = _load(after_path)
    except OSError as exc:
        raise ValueError(f"cannot read {exc.filename}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"not an xping --json file ({exc})") from exc
    result = compare(before, after, max_regression)
    result.before, result.after = before_label, after_label
    if not quiet:
        from xping.render.views import diff as diff_view

        diff_view.print_result(result)
    return result
