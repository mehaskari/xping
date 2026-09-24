"""HTTP diagnostics result rendering — matches the xping visual language."""

from ..ansi import (
    BOLD,
    BRAND_AMBER,
    BRAND_MINT,
    BRAND_ROSE,
    BRAND_SLATE,
    BRAND_TEAL,
    BWHITE,
    DIM,
    c,
)
from ..latency import latency_color


def _status_color(status: int) -> str:
    if 200 <= status < 300:
        return BRAND_MINT
    if 300 <= status < 400:
        return BRAND_AMBER
    return BRAND_ROSE


def _status_badge(status: int, reason: str) -> str:
    color = _status_color(status)
    return c(f" {status} {reason} ", color, BOLD)


def _sub_header(title: str) -> str:
    return c(f"  ── {title} ", BRAND_SLATE, BOLD) + c("─" * max(2, 55 - len(title)), DIM)


def print_result(result) -> None:
    badge = _status_badge(result.status_code, result.reason or "")
    print(f"  {badge}")
    print()

    # ── Redirect chain ────────────────────────────────────────────
    if result.redirects:
        print(_sub_header("Redirect chain"))
        for hop in result.redirects:
            print(
                f"  {c(str(hop.status_code), BRAND_AMBER, BOLD)}  {c('→', BRAND_AMBER)}  {c(hop.url, DIM)}"
            )
        print(
            f"  {c('200', BRAND_MINT, BOLD)}  {c('✔', BRAND_MINT)}  {c(result.final_url or '', BWHITE, BOLD)}"
        )
        print()

    # ── Timing breakdown ──────────────────────────────────────────
    print(_sub_header("Timing"))
    dns_ms = getattr(result, "dns_ms", None)
    tcp_ms = getattr(result, "tcp_ms", None)
    http_ver = getattr(result, "http_version", "HTTP/1.1")
    ttfb = latency_color(result.ttfb_ms) if result.ttfb_ms is not None else c("—", DIM)
    total = latency_color(result.total_ms) if result.total_ms is not None else c("—", DIM)
    h2 = getattr(result, "h2_supported", None)
    print(f"  {c('HTTP version', DIM):<28}  {c(http_ver, BWHITE, BOLD)}")
    if h2 is not None:
        h2_str = c("yes", BRAND_MINT, BOLD) if h2 else c("no", DIM)
        print(f"  {c('HTTP/2 support', DIM):<28}  {h2_str}")
    if dns_ms is not None:
        print(f"  {c('DNS resolve', DIM):<28}  {latency_color(dns_ms)}")
    if tcp_ms is not None:
        print(f"  {c('TCP connect', DIM):<28}  {latency_color(tcp_ms)}")
    print(f"  {c('TTFB', DIM):<28}  {ttfb}")
    print(f"  {c('Total time', DIM):<28}  {total}")
    print(f"  {c('Body size', DIM):<28}  {c(f'{result.body_bytes:,} bytes', BWHITE)}")
    print()

    # ── Headers ───────────────────────────────────────────────────
    if result.headers:
        print(_sub_header("Response headers"))
        priority = {
            "content-type",
            "server",
            "cache-control",
            "content-encoding",
            "location",
            "x-powered-by",
        }
        sorted_headers = sorted(
            result.headers.items(),
            key=lambda kv: (0 if kv[0].lower() in priority else 1, kv[0].lower()),
        )
        for key, value in sorted_headers:
            display_val = value if len(value) <= 72 else value[:69] + c("…", DIM)
            print(f"  {c(key.lower(), BRAND_TEAL):<36}  {c(display_val, BWHITE)}")
        print()

    # ── Summary line ──────────────────────────────────────────────
    redirect_note = (
        f"  {c(f'↪  {result.redirect_count} redirect(s)', BRAND_AMBER)}"
        if result.redirect_count
        else ""
    )
    print(c(f"  ✔  {result.final_url or result.url}", BRAND_MINT) + redirect_note)
    print()
