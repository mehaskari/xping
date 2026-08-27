"""IP sweep result rendering."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_INDIGO, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from ..latency import latency_color
from ..tables import print_table


def print_probe(probe) -> None:
    if probe.alive:
        status = c(" ✔ alive ", BRAND_MINT, BOLD)
        ports = c(",".join(str(port) for port in probe.open_ports), BRAND_INDIGO, BOLD)
        print(
            f"  {status}  {c(probe.ip, BWHITE, BOLD)}  "
            f"ports {ports}  {latency_color(probe.elapsed_ms)}"
        )
    else:
        status = c(" · silent ", DIM)
        print(f"  {status}  {c(probe.ip, BRAND_SLATE)}")


def print_summary(result) -> None:
    badge = (
        c(" ✔ HOSTS FOUND ", BRAND_MINT, BOLD)
        if result.alive_count
        else c(" ✘ NO HOSTS FOUND ", BRAND_ROSE, BOLD)
    )
    print()
    print_table(
        ["Metric", "Value"],
        [
            ["Hosts scanned", c(str(result.scanned), BWHITE)],
            ["Responsive hosts", c(
                str(result.alive_count),
                BRAND_MINT if result.alive_count else BRAND_ROSE,
            )],
            ["Probe ports", c(",".join(str(port) for port in result.ports), BRAND_INDIGO)],
        ],
    )
    if result.alive_hosts:
        print()
        rows = [
            [
                c(host.ip, BRAND_MINT, BOLD),
                c(",".join(str(port) for port in host.open_ports), BRAND_INDIGO),
                latency_color(host.elapsed_ms),
            ]
            for host in result.alive_hosts
        ]
        print_table(["Host", "Open Ports", "Probe time"], rows)
    print()
    print(f"  {badge}  {c(result.target, BWHITE, BOLD)}")
    print()
