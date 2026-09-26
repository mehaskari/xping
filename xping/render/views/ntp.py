"""NTP clock-offset render view (xping ntp)."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from ..latency import latency_color
from ..tables import print_table


def offset_text(ms: float) -> str:
    """Signed offset with a plain-words direction and a colour by size."""
    size = abs(ms)
    color = BRAND_MINT if size < 100 else BRAND_AMBER if size < 1000 else BRAND_ROSE
    value = f"{ms / 1000:+.3f} s" if size >= 1000 else f"{ms:+.1f} ms"
    direction = "your clock is behind" if ms > 0 else "your clock is ahead"
    return c(value, color, BOLD) + (c(f"  ({direction})", DIM) if size >= 1 else "")


def print_sample(sample, total: int) -> None:
    seq = c(f"  [{sample.seq:>{len(str(total))}}]", DIM)
    if sample.offset_ms is None:
        print(f"{seq}  {c(' ✘ ', BRAND_ROSE, BOLD)} {c(sample.error or 'no reply', BRAND_SLATE)}")
        return
    print(
        f"{seq}  {c(' ✔ ', BRAND_MINT, BOLD)} offset {offset_text(sample.offset_ms)}"
        f"   delay {latency_color(sample.delay_ms)}"
    )


def print_summary(result) -> None:
    print()
    if result.error:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
        print()
        return
    sync = (
        c("yes", BRAND_MINT, BOLD)
        if result.synchronized
        else c("NO — server is not synchronised", BRAND_ROSE, BOLD)
    )
    print_table(
        ["Metric", "Value"],
        [
            ["Clock offset", offset_text(result.offset_ms)],
            ["Round-trip delay", latency_color(result.delay_ms)],
            ["Stratum", c(str(result.stratum), BWHITE)],
            ["Reference", c(result.reference or "—", BWHITE)],
            ["Server synchronised", sync],
            ["Replies", f"{len(result.answered)}/{len(result.samples)}"],
        ],
    )
    print()
