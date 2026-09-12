"""Ping result rendering."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BRAND_TEAL, BWHITE, DIM, c
from ..latency import latency_color, latency_histogram, rtt_bar, spark_bar
from ..layout import status_badge, terminal_width
from ..progress import clear_lines
from ..tables import print_table

WATCH_WINDOW = 60


def print_line(seq: int, ip: str, rtt: float, total: int) -> None:
    seq_str = c(f"  [{seq:>{len(str(total))+1}}]", DIM)
    ip_str = c(f"  {ip}", BRAND_SLATE)

    if rtt < 0:
        status = c(" ✘ ", BRAND_ROSE, BOLD)
        rtt_part = c("  timeout", DIM)
        bar_part = ""
    else:
        status = c(" ✔ ", BRAND_MINT, BOLD)
        bar_part = f"  {rtt_bar(rtt)}"
        rtt_part = f"  {latency_color(rtt)}"

    print(f"{seq_str}{status}{ip_str}{bar_part}{rtt_part}")


def redraw_watch(rtts: list[float], printed_rows: int = 0) -> int:
    """Redraw a compact live status line + sparkline in place. Returns the
    new line count to pass back in on the next call."""
    if printed_rows:
        clear_lines(printed_rows)

    window = rtts[-WATCH_WINDOW:]
    seq = len(rtts)
    last = rtts[-1] if rtts else -1.0
    received = sum(1 for r in rtts if r >= 0)
    loss_pct = ((seq - received) / seq * 100) if seq else 0.0
    loss_color = BRAND_MINT if loss_pct == 0 else (BRAND_ROSE if loss_pct > 20 else BRAND_AMBER)

    last_str = latency_color(last) if last >= 0 else c("  timeout", DIM)
    status = c(" ✔ ", BRAND_MINT, BOLD) if last >= 0 else c(" ✘ ", BRAND_ROSE, BOLD)

    line1 = (
        f"  {c(f'#{seq:<5}', BRAND_SLATE)}{status}{last_str}   "
        f"{c('loss', DIM)} {c(f'{loss_pct:.0f}%', loss_color)}"
    )
    line2 = f"  {spark_bar(window)}"

    # running stats
    valid = [r for r in rtts if r >= 0]
    if valid:
        mn = min(valid)
        avg = sum(valid) / len(valid)
        mx = max(valid)
        line3 = (
            f"  {c('min', DIM)} {c(f'{mn:.1f}ms', BRAND_MINT)}"
            f"  {c('avg', DIM)} {c(f'{avg:.1f}ms', BRAND_TEAL)}"
            f"  {c('max', DIM)} {c(f'{mx:.1f}ms', BRAND_ROSE if mx > 100 else BRAND_AMBER)}"
        )
    else:
        line3 = c("  no replies yet", DIM)

    print(line1)
    print(line2)
    print(line3)
    return 3


def print_summary(result) -> None:
    w = terminal_width()
    print()
    print(c("  " + "━" * min(w - 2, 70), BRAND_TEAL))
    print()

    badge = status_badge(result.received > 0)
    loss_color = (
        BRAND_MINT if result.loss_pct == 0
        else BRAND_AMBER if result.loss_pct < 20
        else BRAND_ROSE
    )
    print_table(
        ["Metric", "Value"],
        [
            ["Packets sent", c(str(result.sent), BWHITE)],
            ["Packets received", c(
                str(result.received),
                BRAND_MINT if result.received == result.sent else BRAND_AMBER,
            )],
            ["Packet loss", c(f"{result.loss_pct:.1f}%", loss_color)],
            ["Min RTT", latency_color(result.min_rtt)],
            ["Avg RTT", latency_color(result.avg_rtt)],
            ["Max RTT", latency_color(result.max_rtt)],
            ["Jitter", latency_color(result.jitter)],
            ["Std deviation", latency_color(result.std_dev)],
        ],
    )
    print()

    if result.rtts:
        label = c("  Latency timeline:", BRAND_SLATE)
        spark = spark_bar(result.rtts)
        valid = [v for v in result.rtts if v >= 0]
        scale = (
            c(f"  min {result.min_rtt:.1f} ms", BRAND_MINT)
            + c(" ──── ", DIM)
            + c(f"max {result.max_rtt:.1f} ms", BRAND_ROSE)
        ) if valid else ""
        print(label)
        print(f"  {spark}")
        if scale:
            print(scale)
        print()

        hist = latency_histogram(result.rtts)
        if hist:
            print(c("  Distribution:", BRAND_SLATE))
            print(hist)
    print()
    print(f"  {badge}  {c(result.host, BWHITE, BOLD)}  {c(result.ip, DIM)}")
    print()
