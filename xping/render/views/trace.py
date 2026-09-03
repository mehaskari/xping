"""Traceroute hop rendering."""

from ..ansi import (
    BOLD, BRAND_AMBER, BRAND_INDIGO, BRAND_MINT, BRAND_ROSE,
    BRAND_SLATE, BRAND_TEAL, BWHITE, DIM, c,
)
from ..latency import latency_color
from ..layout import terminal_width
from ..tables import print_table

_HOP_W = 5
_RTT_W = 14
_HOST_W = 48


def hop_header() -> None:
    sep = c("  " + "─" * (_HOP_W + _RTT_W + _HOST_W + 8), DIM)
    hdr = (
        c(f"  {'HOP':>{_HOP_W}}", BRAND_INDIGO, BOLD)
        + c(f"  {'AVG RTT':^{_RTT_W}}", BRAND_INDIGO, BOLD)
        + c(f"  {'HOST / IP':<{_HOST_W}}", BRAND_INDIGO, BOLD)
    )
    print(sep)
    print(hdr)
    print(sep)


def print_hop(hop) -> None:
    if hop.timeout:
        rtt_s = c(f"  {'* * *':^{_RTT_W}}", DIM)
        host_s = c("  no response", DIM)
    else:
        rtt_s = f"  {latency_color(hop.avg_rtt)}"
        label = hop.label or "?"
        if len(label) > _HOST_W - 2:
            label = label[:_HOST_W - 5] + "…"
        host_s = c(f"  {label}", BWHITE)

    hue = (
        BRAND_ROSE if hop.ttl <= 3
        else BRAND_AMBER if hop.ttl <= 8
        else BRAND_TEAL if hop.ttl <= 15
        else BRAND_SLATE
    )
    ttl_icon = c(f"  {hop.ttl:>{_HOP_W}}", hue, BOLD)
    print(f"{ttl_icon}{rtt_s}{host_s}")


def print_summary(hops: list, host: str, dest_ip: str) -> None:
    reached = any(h.ip == dest_ip and not h.timeout for h in hops)
    responding = [h for h in hops if not h.timeout]
    timeouts = [h for h in hops if h.timeout]

    print(c("  " + "─" * 64, DIM))
    print()

    badge = (
        c(" ✔ DESTINATION REACHED ", BRAND_MINT, BOLD)
        if reached
        else c(" ✘ DESTINATION NOT REACHED ", BRAND_ROSE, BOLD)
    )
    print(f"  {badge}  {c(host, BWHITE, BOLD)}")
    print()

    rows = [
        ["Total hops", str(len(hops))],
        ["Responding hops", c(str(len(responding)),
                              BRAND_MINT if responding else BRAND_ROSE)],
        ["Silent hops", c(str(len(timeouts)),
                          DIM if not timeouts else BRAND_AMBER)],
    ]
    if responding:
        last = responding[-1]
        rows.append(["Final responding hop", str(last.ttl)])
        rows.append(["Final hop RTT", latency_color(last.avg_rtt)])
    print_table(["Metric", "Value"], rows)
    print()


def hop_separator() -> None:
    print(c("  " + "─" * 64, DIM))
