"""Pass/fail verdicts for diagnostic results — the basis of xping's exit codes.

Every command's result is judged here, so scripts, cron jobs and monitoring
can rely on `$?`:

    0    the check passed
    1    the check failed (unreachable, error, or a threshold was exceeded)
    2    invalid usage (argparse)
    130  interrupted with Ctrl-C

Thresholds are read from *opts* by attribute name (``max_loss``,
``max_latency``, ``expect_status``, ``min_days``, ``min_score``,
``max_offset``); any that
are missing or None are simply not applied. That lets the same function
serve argparse namespaces and `xping check` config entries alike.
"""

from __future__ import annotations

from dataclasses import dataclass

from xping.models import (
    BlocklistResult,
    BundleResult,
    CheckReport,
    DiffResult,
    DnsCheckResult,
    DnsResult,
    DoctorResult,
    HealthResult,
    Hop,
    HttpResult,
    IpScanResult,
    ListenResult,
    MtrResult,
    MtuResult,
    NetResult,
    NtpResult,
    OsDetectResult,
    PingResult,
    PortScanResult,
    PropagationResult,
    RdnsResult,
    SpeedResult,
    SweepResult,
    TcpResult,
    TlsResult,
    UdpResult,
    WatchResult,
    WhoisResult,
    WifiResult,
)


@dataclass(frozen=True)
class Failure:
    message: str
    threshold: bool = False  # True when caused by a user-supplied threshold


def _opt(opts, name: str):
    return getattr(opts, name, None) if opts is not None else None


def _latency(value: float, limit, what: str) -> list[Failure]:
    if limit is not None and value >= 0 and value > limit:
        return [Failure(f"{what} {value:.1f} ms exceeds --max-latency {limit:g} ms", True)]
    return []


def _ping(r: PingResult, opts) -> list[Failure]:
    if not r.resolved:
        return [Failure(f"cannot resolve '{r.host}'")]
    if r.received == 0:
        return [Failure(f"{r.host} is unreachable (100% packet loss)")]
    failures = []
    max_loss = _opt(opts, "max_loss")
    if max_loss is not None and r.loss_pct > max_loss:
        failures.append(
            Failure(f"packet loss {r.loss_pct:.1f}% exceeds --max-loss {max_loss:g}%", True)
        )
    return failures + _latency(r.avg_rtt, _opt(opts, "max_latency"), "average RTT")


def _tcp(r: TcpResult, opts) -> list[Failure]:
    if not r.resolved:
        return [Failure(r.error or f"cannot resolve '{r.host}'")]
    if r.successful == 0:
        return [Failure(f"{r.host}:{r.port} refused or timed out on every attempt")]
    return _latency(r.avg_connect_ms, _opt(opts, "max_latency"), "average connect time")


def _trace(hops: list, _opts) -> list[Failure]:
    if not hops:
        return [Failure("traceroute produced no hops (unresolvable host or no permission)")]
    return []


def _http(r: HttpResult, opts) -> list[Failure]:
    if r.error:
        return [Failure(r.error)]
    expect = _opt(opts, "expect_status")
    if expect is not None:
        if r.status_code != expect:
            return [Failure(f"HTTP status {r.status_code} != --expect-status {expect}", True)]
    elif r.status_code is None or r.status_code >= 400:
        return [Failure(f"HTTP status {r.status_code}")]
    return _latency(r.total_ms or -1.0, _opt(opts, "max_latency"), "total request time")


def _tls(r: TlsResult, opts) -> list[Failure]:
    if r.error:
        return [Failure(r.error)]
    if r.expired:
        return [Failure("certificate has expired")]
    min_days = _opt(opts, "min_days")
    days = r.days_remaining
    if min_days is not None and days is not None and days < min_days:
        return [Failure(f"certificate expires in {days} days (< --min-days {min_days})", True)]
    return []


def _score(score: int, opts, what: str) -> list[Failure]:
    min_score = _opt(opts, "min_score")
    if min_score is not None and score < min_score:
        return [Failure(f"{what} {score} is below --min-score {min_score}", True)]
    return []


def _health(r: HealthResult, opts) -> list[Failure]:
    if not r.resolved:
        return [Failure(f"cannot resolve '{r.host}'")]
    if r.ping is not None and r.ping.received == 0:
        return [Failure(f"{r.host} is unreachable (100% packet loss)")]
    return _score(r.score, opts, "health score")


def _dnscheck(r: DnsCheckResult, opts) -> list[Failure]:
    if r.error:
        return [Failure(r.error)]
    return _score(r.score, opts, "DNS health score")


def _mtr(r: MtrResult, opts) -> list[Failure]:
    if r.error:
        return [Failure(r.error)]
    dest = next((h for h in reversed(r.hops) if h.ip and h.ip == r.dest_ip), None)
    if dest is None or dest.received == 0:
        return [Failure(f"destination {r.dest_ip} did not respond")]
    max_loss = _opt(opts, "max_loss")
    if max_loss is not None and dest.loss_pct > max_loss:
        return [
            Failure(f"destination loss {dest.loss_pct:.1f}% exceeds --max-loss {max_loss:g}%", True)
        ]
    return _latency(dest.avg, _opt(opts, "max_latency"), "destination average RTT")


def _udp(r: UdpResult, opts) -> list[Failure]:
    if r.error:
        return [Failure(r.error)]
    if r.state == "closed":
        return [Failure(f"{r.host}:{r.port}/udp is closed (ICMP port unreachable)")]
    if r.state != "open":
        return [
            Failure(
                f"no reply from {r.host}:{r.port}/udp (filtered, or the service ignored the probe)"
            )
        ]
    return _latency(r.avg_rtt_ms, _opt(opts, "max_latency"), "average reply time")


def _ntp(r: NtpResult, opts) -> list[Failure]:
    if r.error:
        return [Failure(r.error)]
    if not r.synchronized:
        return [Failure(f"{r.server} is not synchronised (stratum {r.stratum}, leap {r.leap})")]
    limit = _opt(opts, "max_offset")
    if limit is not None and r.offset_ms is not None and abs(r.offset_ms) > limit:
        return [
            Failure(f"clock offset {r.offset_ms:+.1f} ms exceeds --max-offset {limit:g} ms", True)
        ]
    return []


def _blocklist(r: BlocklistResult, _opts) -> list[Failure]:
    if r.error:
        return [Failure(r.error)]
    if r.listed:
        return [Failure(f"{r.target} is listed on: " + ", ".join(r.listed))]
    return []


def _diff(r: DiffResult, _opts) -> list[Failure]:
    if r.error:
        return [Failure(r.error)]
    if r.max_regression is not None and r.regressions:
        return [Failure("regression: " + ", ".join(r.regressions), True)]
    return []


def _wifi(r: WifiResult, opts) -> list[Failure]:
    if r.error or not r.current:
        return [Failure(r.error or "not connected to Wi-Fi")]
    limit = _opt(opts, "min_signal")
    signal = r.current.signal_dbm
    if limit is not None and signal is not None and signal < limit:
        return [Failure(f"Wi-Fi signal {signal} dBm is below --min-signal {limit} dBm", True)]
    return []


def _bundle(r: BundleResult, opts) -> list[Failure]:
    failures: list[Failure] = []
    if r.lookup is not None and r.lookup.error:
        failures.append(Failure(f"DNS: {r.lookup.error}"))
    if r.ping is not None:
        failures += _ping(r.ping, None)
    if r.tcp and all(t.successful == 0 for t in r.tcp):
        failures.append(Failure("no TCP port (443, 80) accepted a connection"))
    return failures


def _scan(r, what: str) -> list[Failure]:
    if r.error:
        return [Failure(r.error)]
    if r.alive_count == 0:
        return [Failure(f"no {what} found in {r.target}")]
    return []


def _errored(r) -> list[Failure]:
    return [Failure(r.error)] if getattr(r, "error", None) else []


def evaluate(result, opts=None) -> list[Failure]:
    """Return why *result* counts as a failure (empty list = success)."""
    if result is None or result is True:
        return []
    if result is False:
        return [Failure("operation failed")]
    if isinstance(result, list):
        if result and not all(isinstance(h, Hop) for h in result):
            return []
        return _trace(result, opts)

    handlers = (
        (PingResult, _ping),
        (TcpResult, _tcp),
        (HttpResult, _http),
        (TlsResult, _tls),
        (HealthResult, _health),
        (DnsCheckResult, _dnscheck),
        (MtrResult, _mtr),
        (BundleResult, _bundle),
        (UdpResult, _udp),
        (DiffResult, _diff),
        (WifiResult, _wifi),
        (BlocklistResult, _blocklist),
        (NtpResult, _ntp),
    )
    for cls, handler in handlers:
        if isinstance(result, cls):
            return handler(result, opts)

    if isinstance(result, SweepResult):
        return _scan(result, "hosts with open ports")
    if isinstance(result, IpScanResult):
        return _scan(result, "live hosts")
    if isinstance(result, PortScanResult):
        return [Failure(result.error or "cannot resolve host")] if not result.resolved else []
    if isinstance(result, DnsResult | RdnsResult | WhoisResult | MtuResult | OsDetectResult):
        return _errored(result)
    if isinstance(result, ListenResult | NetResult):
        return _errored(result)
    if isinstance(result, DoctorResult):
        return [] if result.ok else [Failure(result.diagnosis)]
    if isinstance(result, CheckReport):
        if result.ok:
            return []
        return [Failure(f"{result.failed} of {len(result.outcomes)} checks failed")]
    if isinstance(result, WatchResult):
        if result.last_ok:
            return []
        return [Failure(f"{result.target} was down at the last check")]
    if isinstance(result, PropagationResult):
        return [Failure(message, threshold) for message, threshold in result.problems()]
    if isinstance(result, SpeedResult):
        if result.error:
            return [Failure(result.error)]
        if result.download_mbps is None:
            return [Failure("download measurement failed")]
        return []
    return []
