"""Latency colour coding, sparklines, and RTT bars."""

from .ansi import (
    BOLD,
    BRAND_AMBER,
    BRAND_MINT,
    BRAND_ROSE,
    BYELLOW,
    DIM,
    c,
)


def latency_color(ms: float) -> str:
    """Color-code a latency value."""
    if ms < 0:
        return c("timeout", DIM)
    val = f"{ms:.2f} ms"
    if ms < 30:
        return c(val, BRAND_MINT, BOLD)
    if ms < 100:
        return c(val, BRAND_AMBER, BOLD)
    if ms < 300:
        return c(val, BYELLOW)
    return c(val, BRAND_ROSE)


def spark_bar(values: list[float], width: int = 30) -> str:
    """Render a mini sparkline bar for latency samples."""
    if not values:
        return ""
    valid = [v for v in values if v >= 0]
    if not valid:
        return c("  no data", DIM)
    lo, hi = min(valid), max(valid)
    blocks = " ▁▂▃▄▅▆▇█"
    result = []
    for v in values:
        if v < 0:
            result.append(c("·", DIM))
        else:
            idx = int((v - lo) / (hi - lo + 0.001) * 8)
            ch = blocks[idx]
            result.append(latency_color(v).replace(f"{v:.2f} ms", ch))
    return "".join(result)


def latency_histogram(rtts: list[float]) -> str:
    """Render a compact horizontal latency distribution histogram."""
    valid = [v for v in rtts if v >= 0]
    if not valid:
        return ""
    buckets = [
        ("0-10ms  ", 0, 10, BRAND_MINT),
        ("10-30ms ", 10, 30, BRAND_MINT),
        ("30-100ms", 30, 100, BRAND_AMBER),
        ("100-300ms", 100, 300, BYELLOW),
        (">300ms  ", 300, float("inf"), BRAND_ROSE),
    ]
    counts = []
    for _label, lo, hi, _color in buckets:
        counts.append(sum(1 for v in valid if lo <= v < hi))
    max_count = max(counts) if counts else 1
    bar_width = 20
    lines = []
    for (label, _lo, _hi, color), count in zip(buckets, counts, strict=True):
        if count == 0:
            continue
        filled = max(1, round(count / max_count * bar_width))
        bar = c("█" * filled, color)
        num = c(f"  {count}", DIM)
        lines.append(f"  {c(label, DIM)}  {bar}{num}")
    return "\n".join(lines)


def rtt_bar(rtt: float, width: int = 36) -> str:
    """Render a filled latency bar proportional to RTT (max ~500 ms = full)."""
    if rtt < 0:
        return c("─" * width, DIM)
    filled = min(int(rtt / 500 * width), width)
    empty = width - filled
    bar_color = (
        BRAND_MINT
        if rtt < 30
        else BRAND_AMBER
        if rtt < 100
        else BYELLOW
        if rtt < 300
        else BRAND_ROSE
    )
    return c("█" * filled, bar_color) + c("░" * empty, DIM)
