"""Network health score rendering."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_INDIGO, BRAND_MINT, BRAND_ROSE, BWHITE, BYELLOW, DIM, c
from ..latency import latency_color
from ..tables import print_table

_GRADE_COLOR = {
    "Excellent": BRAND_MINT,
    "Good": BRAND_MINT,
    "Fair": BYELLOW,
    "Poor": BRAND_AMBER,
    "Critical": BRAND_ROSE,
}


def _score_bar(score: int, grade: str, width: int = 40) -> str:
    filled = round(score / 100 * width)
    color = _GRADE_COLOR.get(grade, BWHITE)
    return c("█" * filled, color) + c("░" * (width - filled), DIM)


def _trend_arrow(scores: list) -> str:
    if len(scores) < 2:
        return ""
    delta = scores[-1] - scores[-2]
    if delta > 3:
        return c("  ↑", BRAND_MINT, BOLD)
    if delta < -3:
        return c("  ↓", BRAND_ROSE, BOLD)
    return c("  →", DIM)


def _score_spark(scores: list) -> str:
    blocks = " ▁▂▃▄▅▆▇█"
    lo, hi = min(scores), max(scores)
    span = hi - lo if hi != lo else 1
    result = []
    for s in scores:
        idx = int((s - lo) / span * 8)
        grade = (
            "Excellent"
            if s >= 90
            else "Good"
            if s >= 75
            else "Fair"
            if s >= 50
            else "Poor"
            if s >= 25
            else "Critical"
        )
        result.append(c(blocks[idx], _GRADE_COLOR.get(grade, BWHITE)))
    return "".join(result)


def print_summary(result) -> None:
    color = _GRADE_COLOR.get(result.grade, BWHITE)

    print(c("  " + "─" * 64, DIM))
    print()
    print(
        f"  {c(str(result.score), color, BOLD)}{c('/100', DIM)}   "
        f"{c(result.grade.upper(), color, BOLD)}"
    )
    print(f"  {_score_bar(result.score, result.grade)}")
    print()

    p = result.ping
    rows = [
        ["DNS resolve", f"{result.dns_resolve_ms:.1f} ms"],
        ["Packet loss", f"{p.loss_pct:.0f}%"],
        ["Avg latency", latency_color(p.avg_rtt) if p.avg_rtt >= 0 else "—"],
        ["Jitter", latency_color(p.jitter)],
    ]
    print_table(["Metric", "Value"], rows)
    print()

    if result.issues:
        print(c("  Findings:", BWHITE, BOLD))
        for issue in result.issues:
            print(c(f"   • {issue}", BRAND_AMBER))
    else:
        print(c("  No issues detected — connection looks healthy.", BRAND_MINT))
    print()

    # History trend
    history = getattr(result, "history", None)
    if history and len(history) >= 2:
        scores = [h["score"] for h in history[-10:]]
        arrow = _trend_arrow(scores)
        spark = _score_spark(scores)
        print(c("  Score history:", BRAND_INDIGO, BOLD) + arrow)
        print(f"  {spark}")
        print(
            c(
                f"  Last {len(scores)} checks — "
                f"min {min(scores)}  avg {sum(scores) // len(scores)}  max {max(scores)}",
                DIM,
            )
        )
        print()
