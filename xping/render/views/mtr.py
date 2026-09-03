"""Live MTR (combined traceroute + ping) rendering."""

from ..ansi import BOLD, BRAND_INDIGO, BRAND_MINT, BRAND_ROSE, BWHITE, DIM, c
from ..latency import latency_color, spark_bar
from ..progress import clear_lines
from ..tables import print_table

_HEADERS = ["TTL", "Host", "Loss%", "Sent", "Last", "Avg", "Best", "Worst", "StDev"]


def _fmt(value: float) -> str:
    return f"{value:.1f}" if value >= 0 else "—"


def _rows_for(hops: list) -> list[list[str]]:
    rows = []
    for hop in hops:
        if not hop.ip:
            rows.append([str(hop.ttl), c("* * *", DIM), "—", str(hop.sent),
                         "—", "—", "—", "—", "—"])
            continue
        loss_color = (
            BRAND_MINT if hop.loss_pct == 0
            else BRAND_ROSE if hop.loss_pct >= 50
            else BWHITE
        )
        rows.append([
            str(hop.ttl),
            hop.label,
            c(f"{hop.loss_pct:.0f}%", loss_color),
            str(hop.sent),
            latency_color(hop.last) if hop.last >= 0 else c("—", DIM),
            latency_color(hop.avg) if hop.avg >= 0 else c("—", DIM),
            latency_color(hop.best) if hop.best >= 0 else c("—", DIM),
            latency_color(hop.worst) if hop.worst >= 0 else c("—", DIM),
            c(f"{hop.stdev:.1f}", DIM) if hop.stdev > 0 else c("—", DIM),
        ])
    return rows


def redraw(hops: list, cycle: int, total_cycles: int, printed_rows: int = 0) -> int:
    """Redraw the live MTR table in place. Returns the new line count."""
    if printed_rows:
        clear_lines(printed_rows)

    print(c(f"  Cycle {cycle}/{total_cycles}", BRAND_INDIGO, BOLD))
    print()
    rows = _rows_for(hops)
    print_table(_HEADERS, rows)
    return len(rows) + 6


def print_final(hops: list) -> None:
    print()
    print(c("  Final results:", BWHITE, BOLD))
    print_table(_HEADERS, _rows_for(hops))
    print()

    # Per-hop sparkline summary
    responding = [h for h in hops if h.ip and h.rtts]
    if responding:
        print(c("  Latency per hop:", BRAND_INDIGO, BOLD))
        for hop in responding:
            label = (hop.host or hop.ip or "???")[:28]
            spark = spark_bar(hop.rtts)
            print(f"  {c(f'{hop.ttl:>2}', DIM)}  {c(f'{label:<30}', BWHITE)}  {spark}")
        print()
