"""IP scan result rendering."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from ..latency import latency_color
from ..tables import print_table


def print_probe(probe) -> None:
    if probe.alive:
        status = c(" ✔ alive ", BRAND_MINT, BOLD)
        rtt = latency_color(probe.rtt_ms if probe.rtt_ms >= 0 else probe.elapsed_ms)
        print(f"  {status}  {c(probe.ip, BWHITE, BOLD)}  {rtt}")
    else:
        status = c(" · silent ", DIM)
        detail = c(probe.error or "no reply", DIM)
        print(f"  {status}  {c(probe.ip, BRAND_SLATE)}  {detail}")


def print_summary(result) -> None:
    badge = (
        c(" ✔ LIVE HOSTS FOUND ", BRAND_MINT, BOLD)
        if result.alive_count
        else c(" ✘ NO LIVE HOSTS FOUND ", BRAND_ROSE, BOLD)
    )
    print()
    print_table(
        ["Metric", "Value"],
        [
            ["IPs scanned", c(str(result.scanned), BWHITE)],
            ["Live hosts", c(
                str(result.alive_count),
                BRAND_MINT if result.alive_count else BRAND_ROSE,
            )],
            ["Silent hosts", c(
                str(result.scanned - result.alive_count),
                DIM if result.alive_count == result.scanned else BRAND_AMBER,
            )],
        ],
    )
    if result.alive_hosts:
        print()
        rows = [
            [
                c(probe.ip, BRAND_MINT, BOLD),
                latency_color(probe.rtt_ms if probe.rtt_ms >= 0 else probe.elapsed_ms),
            ]
            for probe in result.alive_hosts
        ]
        print_table(["IP", "RTT"], rows)
    print()
    print(f"  {badge}  {c(result.target, BWHITE, BOLD)}")
    print()
