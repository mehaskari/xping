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
    if name == "UdpResult":
        return f"replied in {result.avg_rtt_ms:.1f} ms"
    if name == "NtpResult":
        return f"clock offset {result.offset_ms:+.1f} ms, stratum {result.stratum}"
    if name == "PropagationResult":
        answered = len(result.answered)
        if result.expected:
            return f"{result.matching}/{answered} resolvers match"
        return f"{answered} resolvers, {result.distinct_answers} distinct answer(s)"
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
