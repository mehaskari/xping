"""Port scan result rendering."""

from ..ansi import (
    BOLD,
    BRAND_AMBER,
    BRAND_INDIGO,
    BRAND_MINT,
    BRAND_ROSE,
    BRAND_SLATE,
    BWHITE,
    DIM,
    c,
)
from ..latency import latency_color
from ..tables import print_table


def print_port_result(result) -> None:
    service = c(result.service or "-", BRAND_SLATE)
    if result.open:
        status = c(" OPEN ", BRAND_MINT, BOLD)
        timing = latency_color(result.elapsed_ms)
        banner_str = c(f"  {result.banner[:55]}", DIM) if result.banner else ""
        print(
            f"  {c(str(result.port).rjust(5), BRAND_INDIGO, BOLD)}  "
            f"{status}  {service}  {timing}{banner_str}"
        )
    else:
        status = c(" closed ", DIM)
        detail = c(result.error or "no response", DIM)
        print(f"  {c(str(result.port).rjust(5), DIM)}  {status}  {service}  {detail}")


def print_summary(result) -> None:
    open_count = len(result.open_ports)
    badge = (
        c(" ✔ OPEN PORTS FOUND ", BRAND_MINT, BOLD)
        if open_count
        else c(" ✘ NO OPEN PORTS FOUND ", BRAND_ROSE, BOLD)
    )
    print()
    print_table(
        ["Metric", "Value"],
        [
            ["Ports scanned", c(str(result.scanned), BWHITE)],
            ["Open ports", c(str(open_count), BRAND_MINT if open_count else BRAND_ROSE)],
            [
                "Closed/filtered",
                c(
                    str(result.closed_ports),
                    DIM if open_count == result.scanned else BRAND_AMBER,
                ),
            ],
        ],
    )
    if result.open_ports:
        print()
        has_banners = any(item.banner for item in result.open_ports)
        if has_banners:
            rows = [
                [
                    c(str(item.port), BRAND_MINT, BOLD),
                    c(item.service or "-", BRAND_SLATE),
                    latency_color(item.elapsed_ms),
                    c(item.banner or "—", DIM),
                ]
                for item in result.open_ports
            ]
            print_table(["Port", "Service", "Connect", "Banner"], rows)
        else:
            rows = [
                [
                    c(str(item.port), BRAND_MINT, BOLD),
                    c(item.service or "-", BRAND_SLATE),
                    latency_color(item.elapsed_ms),
                ]
                for item in result.open_ports
            ]
            print_table(["Port", "Service", "Connect time"], rows)
    print()
    print(f"  {badge}  {c(result.host, BWHITE, BOLD)}  {c(result.ip, DIM)}")
    print()
