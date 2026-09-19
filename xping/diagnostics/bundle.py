"""Run the full host diagnostic bundle."""

from xping.diagnostics.lookup import lookup
from xping.diagnostics.ping import ping
from xping.diagnostics.tcp import tcp
from xping.diagnostics.trace import trace
from xping.models.bundle import BundleResult
from xping.render import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from xping.render.latency import latency_color


def _bundle_summary(result: BundleResult) -> None:
    """Print a unified one-screen summary after all diagnostics finish."""
    print()
    print(c("  ══ SUMMARY ", BRAND_SLATE, BOLD) + c("═" * 52, DIM))
    print()

    # DNS
    dns = result.lookup
    if dns and dns.ipv4:
        ip_str = dns.ipv4[0]
        extras = f"  (+{len(dns.ipv4) - 1} more)" if len(dns.ipv4) > 1 else ""
        print(
            f"  {c('DNS', BRAND_SLATE):<24}  {c('✔', BRAND_MINT)}  "
            f"{c(ip_str, BWHITE)}{c(extras, DIM)}"
        )
    elif dns and dns.error:
        print(f"  {c('DNS', BRAND_SLATE):<24}  {c('✘', BRAND_ROSE)}  {c(dns.error, DIM)}")

    # Ping
    p = result.ping
    if p and p.resolved:
        loss_color = (
            BRAND_MINT if p.loss_pct == 0 else (BRAND_ROSE if p.loss_pct > 20 else BRAND_AMBER)
        )
        ping_ok = p.received > 0
        badge = c("✔", BRAND_MINT) if ping_ok else c("✘", BRAND_ROSE)
        detail = f"{latency_color(p.avg_rtt)} avg   {c(f'{p.loss_pct:.0f}% loss', loss_color)}"
        print(f"  {c('Ping', BRAND_SLATE):<24}  {badge}  {detail}")

    # Trace
    if result.trace:
        hops = len(result.trace)
        dest_ip = result.lookup.ipv4[0] if result.lookup and result.lookup.ipv4 else None
        reached = any(h.ip == dest_ip and not h.timeout for h in result.trace) if dest_ip else False
        badge = c("✔", BRAND_MINT) if reached else c("~", BRAND_AMBER)
        status = "reached" if reached else "incomplete"
        print(
            f"  {c('Trace', BRAND_SLATE):<24}  {badge}  "
            f"{c(f'{hops} hops', BWHITE)}  {c(status, DIM)}"
        )

    # TCP checks
    for tcp_r in result.tcp:
        port_label = f"TCP {tcp_r.port}"
        if tcp_r.resolved and tcp_r.successful > 0:
            badge = c("✔", BRAND_MINT)
            detail = latency_color(tcp_r.avg_connect_ms)
        elif not tcp_r.resolved:
            badge = c("✘", BRAND_ROSE)
            detail = c("unresolved", DIM)
        else:
            badge = c("✘", BRAND_ROSE)
            detail = c("refused / timeout", DIM)
        print(f"  {c(port_label, BRAND_SLATE):<24}  {badge}  {detail}")

    print()


def run_bundle(host: str, *, quiet: bool = False) -> BundleResult:
    """Run lookup, ping, trace, and common TCP checks for a host."""
    dns = lookup(host=host, full=True, quiet=quiet)
    icmp = ping(host=host, count=4, quiet=quiet)
    hops = trace(host=host, quiet=quiet)
    tcp_checks = [
        tcp(host=host, port=443, count=2, quiet=quiet),
        tcp(host=host, port=80, count=2, quiet=quiet),
    ]
    result = BundleResult(host=host, lookup=dns, ping=icmp, trace=hops, tcp=tcp_checks)
    if not quiet:
        _bundle_summary(result)
    return result
