"""Batch check (xping check) render view."""

from ..ansi import BOLD, BRAND_MINT, BRAND_ROSE, BWHITE, DIM, c
from ..tables import print_table


def describe(result) -> str:
    """One-line success summary for a passing check."""
    name = type(result).__name__
    if name == "PingResult":
        return f"avg {result.avg_rtt:.1f} ms, {result.loss_pct:.0f}% loss"
    if name == "TcpResult":
        return f"connected in {result.avg_connect_ms:.1f} ms"
    if name == "HttpResult":
        return f"HTTP {result.status_code} in {result.total_ms or 0:.0f} ms"
    if name == "TlsResult":
        return f"{result.protocol}, expires in {result.days_remaining} days"
    if name == "DnsResult":
        count = len(result.ipv4) + len(result.ipv6)
        return f"{count} address record(s)"
    if name == "DnsCheckResult":
        return f"score {result.score} ({result.grade})"
    if name == "HealthResult":
        return f"score {result.score} ({result.grade})"
    if name == "BlocklistResult":
        return f"not listed ({result.answered} lists answered)"
    if name == "SmtpResult":
        return f"{result.banner_code} {'TLS ' + result.tls_version if result.tls else 'no TLS'}"
    if name == "UdpResult":
        return f"replied in {result.avg_rtt_ms:.1f} ms"
    if name == "NtpResult":
        return f"clock offset {result.offset_ms:+.1f} ms, stratum {result.stratum}"
    if name == "PropagationResult":
        answered = len(result.answered)
        if result.expected:
            return f"{result.matching}/{answered} resolvers match"
        return f"{answered} resolvers, {result.distinct_answers} distinct answer(s)"
    if name == "list":  # trace hops
        last = result[-1] if result else None
        rtts = [r for r in (last.rtts if last else []) if r >= 0]
        rtt = f", {min(rtts):.1f} ms" if rtts else ""
        return f"{len(result)} hops to {last.ip if last and last.ip else '?'}{rtt}"
    if name == "MtrResult":
        dest = next((h for h in reversed(result.hops) if h.ip == result.dest_ip), None)
        if dest is None:
            return f"{len(result.hops)} hops"
        return f"{len(result.hops)} hops, avg {dest.avg:.1f} ms, {dest.loss_pct:.0f}% loss"
    if name == "WifiResult":
        net = result.current
        ssid = (net.ssid if net else None) or "connected"
        signal = f", {net.signal_dbm} dBm" if net and net.signal_dbm is not None else ""
        return f"{ssid}{signal}"
    if name == "DoctorResult":
        return result.diagnosis or "ok"
    if name == "SpeedResult":
        up = f"{result.upload_mbps:.1f}" if result.upload_mbps is not None else "–"
        return f"↓ {result.download_mbps:.1f}  ↑ {up} Mbit/s"
    return "ok"


def print_report(report) -> None:
    rows = []
    for o in report.outcomes:
        status = c("✔ PASS", BRAND_MINT, BOLD) if o.ok else c("✘ FAIL", BRAND_ROSE, BOLD)
        detail = c(o.detail, DIM) if o.ok else c(o.detail, BRAND_ROSE)
        rows.append(
            [
                status,
                c(o.name, BWHITE, BOLD),
                o.type,
                c(o.target, DIM),
                detail,
                f"{o.elapsed_ms:.0f} ms",
            ]
        )
    print_table(["Status", "Check", "Type", "Target", "Detail", "Time"], rows)
    print()
    total = len(report.outcomes)
    if report.ok:
        print(c(f"  ✔ All {total} checks passed", BRAND_MINT, BOLD))
    else:
        print(c(f"  ✘ {report.failed} of {total} checks failed", BRAND_ROSE, BOLD))
    print()
