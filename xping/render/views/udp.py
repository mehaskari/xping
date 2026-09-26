"""UDP probe render view (xping udp)."""

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

_STATE = {
    "open": (" ✔ open ", BRAND_MINT),
    "closed": (" ✘ closed ", BRAND_ROSE),
    "no-response": (" ? no response ", BRAND_AMBER),
}
_BADGE = {
    "open": (" ✔ UDP SERVICE ANSWERED ", BRAND_MINT),
    "closed": (" ✘ PORT CLOSED ", BRAND_ROSE),
    "no-response": (" ? NO RESPONSE — OPEN|FILTERED ", BRAND_AMBER),
}


def print_attempt(attempt, total: int) -> None:
    seq = c(f"  [{attempt.seq:>{len(str(total))}}]", DIM)
    label, color = _STATE[attempt.state]
    timing = f"  {latency_color(attempt.rtt_ms)}" if attempt.state == "open" else ""
    print(f"{seq}  {c(label, color, BOLD)}{timing}  {c(attempt.detail, BRAND_SLATE)}")


def print_summary(result) -> None:
    print()
    print_table(
        ["Metric", "Value"],
        [
            ["Attempts", c(str(len(result.attempts)), BWHITE)],
            ["Replies", c(str(result.replies), BRAND_MINT if result.replies else BRAND_ROSE)],
            ["Avg reply time", latency_color(result.avg_rtt_ms)],
            ["Probe", c(result.probe, BWHITE)],
        ],
    )
    print()
    label, color = _BADGE[result.state]
    print(
        f"  {c(label, color, BOLD)}  {c(result.host, BWHITE, BOLD)}:{c(str(result.port), BRAND_INDIGO, BOLD)}"
    )
    if result.state == "no-response":
        print(
            c(
                "  UDP cannot tell a filtered port from a service that ignores this request;"
                " try --probe or --payload.",
                DIM,
            )
        )
    print()
