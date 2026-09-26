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

_SECURITY_BADGES = {
    "ok": ("✔", BRAND_MINT),
    "warn": ("!", BRAND_AMBER),
    "missing": ("✘", BRAND_ROSE),
}
_BAR_WIDTH = 30


def timing_rows(result) -> list[tuple[str, float | None, str]]:
    """(label, ms, waterfall bar) per phase of the final request; each bar
    starts where the previous phase ended, like a browser's network tab."""
    phases = [
        ("Redirects", result.redirect_ms),
        ("DNS lookup", result.dns_ms),
        ("TCP connect", result.tcp_ms),
        ("TLS handshake", result.tls_ms),
        ("Server response", result.ttfb_ms),
        ("Download", result.transfer_ms),
    ]
    phases = [(label, ms) for label, ms in phases if ms is not None]
    span = sum(ms for _, ms in phases) or 1.0
    rows, elapsed = [], 0.0
    for label, ms in phases:
        start = min(round(elapsed / span * _BAR_WIDTH), _BAR_WIDTH - 1)
        length = min(max(1, round(ms / span * _BAR_WIDTH)), _BAR_WIDTH - start)
        rows.append((label, ms, " " * start + "█" * length))
        elapsed += ms
    return rows


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
        final = result.status_code or 0
        print(
            f"  {c(str(final), _status_color(final), BOLD)}  {c('✔', _status_color(final))}"
            f"  {c(result.final_url or '', BWHITE, BOLD)}"
        )
        print()

    # ── Timing breakdown (waterfall) ──────────────────────────────
    print(_sub_header("Timing"))
    for label, ms, bar in timing_rows(result):
        value = latency_color(ms) if ms is not None else c("—", DIM)
        print(f"  {c(label, DIM):<28}  {value:<22}  {c(bar, BRAND_TEAL)}")
    total = latency_color(result.total_ms) if result.total_ms is not None else c("—", DIM)
    print(f"  {c('Total', BWHITE, BOLD):<30}{total}")
    print()

    print(_sub_header("Connection"))
    http_ver = result.http_version or "HTTP/1.1"
    print(f"  {c('HTTP version', DIM):<28}  {c(http_ver, BWHITE, BOLD)}")
    if result.h2_supported is not None:
        h2_str = c("yes", BRAND_MINT, BOLD) if result.h2_supported else c("no", DIM)
        print(f"  {c('HTTP/2 support', DIM):<28}  {h2_str}")
    if result.tls_version:
        tls = result.tls_version + (f"  {result.tls_cipher}" if result.tls_cipher else "")
        print(f"  {c('TLS', DIM):<28}  {c(tls, BWHITE)}")
    if result.ip:
        print(f"  {c('Server IP', DIM):<28}  {c(result.ip, BWHITE)}")
    print(f"  {c('Body size', DIM):<28}  {c(f'{result.body_bytes:,} bytes', BWHITE)}")
    print()

    # ── Security headers ──────────────────────────────────────────
    if result.security:
        good = sum(1 for h in result.security if h.status == "ok")
        print(_sub_header(f"Security headers  {good}/{len(result.security)}"))
        for item in result.security:
            icon, color = _SECURITY_BADGES.get(item.status, ("?", DIM))
            if item.status == "missing":
                shown = item.note or "not set"
            elif item.value and item.note:
                shown = f"{item.value}  ({item.note})"
            else:
                shown = item.value or item.note
            if shown and len(shown) > 60:
                shown = shown[:57] + "…"
            print(f"  {c(icon, color, BOLD)}  {c(item.name, BWHITE):<40}  {c(shown or '', DIM)}")
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
