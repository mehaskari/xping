"""TLS inspector result rendering."""

import ssl
import time

from ..ansi import BOLD, BRAND_AMBER, BRAND_INDIGO, BRAND_MINT, BRAND_ROSE, BWHITE, DIM, c
from ..tables import print_table


def _expiry_badge(result) -> str:
    if result.expired:
        return c(" ✘ EXPIRED ", BRAND_ROSE, BOLD)
    if result.expiring_soon:
        return c(" ⚠ EXPIRING SOON ", BRAND_AMBER, BOLD)
    return c(" ✔ VALID ", BRAND_MINT, BOLD)


def _lifetime_bar(not_before: str, not_after: str, width: int = 36) -> str:
    """Show how much of the certificate's lifetime has been consumed."""
    try:
        start = ssl.cert_time_to_seconds(not_before)
        end = ssl.cert_time_to_seconds(not_after)
        now = time.time()
        total = end - start
        if total <= 0:
            return ""
        used_pct = max(0.0, min(1.0, (now - start) / total))
        filled = round(used_pct * width)
        remaining_pct = 1.0 - used_pct
        bar_color = (
            BRAND_MINT if remaining_pct > 0.3
            else BRAND_AMBER if remaining_pct > 0.1
            else BRAND_ROSE
        )
        bar = c("█" * filled, bar_color) + c("░" * (width - filled), DIM)
        pct_str = c(f"{used_pct * 100:.0f}% of lifetime used", DIM)
        return f"  {bar}  {pct_str}"
    except (ValueError, OverflowError, OSError):
        return ""


def _expiry_date(not_after: str) -> str:
    """Parse the cert expiry and return a formatted date string."""
    try:
        ts = ssl.cert_time_to_seconds(not_after)
        return time.strftime("%Y-%m-%d", time.gmtime(ts))
    except Exception:
        return not_after


def print_result(result) -> None:
    badge = _expiry_badge(result)
    print(f"  {badge}  {c(result.host, BWHITE, BOLD)}")
    print()

    days = result.days_remaining
    if days is not None:
        expiry_date = _expiry_date(result.not_after) if result.not_after else "?"
        day_color = BRAND_ROSE if result.expired else (BRAND_AMBER if result.expiring_soon else BWHITE)
        days_s = c(f"{days} days", day_color, BOLD) + c(f"  ({expiry_date})", DIM)
    else:
        days_s = c("unknown", DIM)

    rows = [
        ["Protocol",     result.protocol or "—"],
        ["Cipher",       result.cipher or "—"],
        ["Subject",      result.subject or "—"],
        ["Issuer",       result.issuer or "—"],
        ["Valid from",   result.not_before or "—"],
        ["Valid until",  result.not_after or "—"],
        ["Expires in",   days_s],
    ]
    if result.san:
        names = ", ".join(result.san[:6])
        if len(result.san) > 6:
            names += f"  (+{len(result.san) - 6} more)"
        rows.append(["Alt names", names])

    print_table(["Field", "Value"], rows)

    # Certificate chain
    chain = getattr(result, "chain", [])
    if len(chain) > 1:
        print(c("  Certificate chain:", BRAND_INDIGO, BOLD))
        for i, name in enumerate(chain):
            connector = "  └─" if i == len(chain) - 1 else "  ├─"
            label = c("leaf  ", BRAND_MINT) if i == 0 else c(f"CA {i}  ", DIM)
            print(f"{c(connector, DIM)} {label}{c(name, BWHITE)}")
        print()

    # Lifetime progress bar
    if result.not_before and result.not_after:
        bar = _lifetime_bar(result.not_before, result.not_after)
        if bar:
            print(bar)
    print()
