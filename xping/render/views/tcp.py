"""TCP connectivity result rendering."""

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
from ..latency import latency_color, spark_bar
from ..tables import print_table


def print_line(attempt, total: int) -> None:
    seq = c(f"  [{attempt.seq:>{len(str(total))}}]", DIM)
    if attempt.ok:
        status = c(" ✔ open ", BRAND_MINT, BOLD)
        timing = latency_color(attempt.elapsed_ms)
        print(f"{seq}  {status}  connected in {timing}")
    else:
        status = c(" ✘ failed ", BRAND_ROSE, BOLD)
        detail = c(attempt.error or "connection failed", BRAND_SLATE)
        print(f"{seq}  {status}  {detail}")


def print_summary(result) -> None:
    print()
    badge = (
        c(" ✔ PORT REACHABLE ", BRAND_MINT, BOLD)
        if result.successful
        else c(" ✘ PORT UNREACHABLE ", BRAND_ROSE, BOLD)
    )
    success_color = (
        BRAND_MINT
        if result.success_pct == 100
        else BRAND_AMBER
        if result.success_pct > 0
        else BRAND_ROSE
    )

    print_table(
        ["Metric", "Value"],
        [
            ["Attempts", c(str(result.count), BWHITE)],
            [
                "Successful",
                c(str(result.successful), BRAND_MINT if result.successful else BRAND_ROSE),
            ],
            ["Failed", c(str(result.failed), DIM if result.failed == 0 else BRAND_AMBER)],
            ["Success rate", c(f"{result.success_pct:.1f}%", success_color)],
            ["Min connect", latency_color(result.min_connect_ms)],
            ["Avg connect", latency_color(result.avg_connect_ms)],
            ["Max connect", latency_color(result.max_connect_ms)],
        ],
    )

    if result.connect_times:
        print()
        print(c("  Connect timeline:", BRAND_SLATE))
        print(f"  {spark_bar(result.connect_times)}")

    print()
    print(f"  {badge}  {c(result.host, BWHITE, BOLD)}:{c(str(result.port), BRAND_INDIGO, BOLD)}")
    print()
