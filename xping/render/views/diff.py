"""Run comparison render view (xping diff)."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from ..layout import kv, section_header
from ..tables import print_table

_VERDICT = {"better": BRAND_MINT, "worse": BRAND_ROSE, "changed": BRAND_AMBER, "same": DIM}
_ARROW = {"better": "▲ better", "worse": "▼ worse", "changed": "changed"}


def _value(value, unit: str) -> str:
    if value is None:
        return "—"
    text = (
        f"{value:,.0f}"
        if unit in ("bytes", "", "days") and value == int(value)
        else f"{value:,.2f}"
    )
    return f"{text} {unit}".strip()


def _change(m) -> str:
    color = _VERDICT[m.verdict]
    if m.verdict == "same":
        return c("same", DIM)
    if m.before is None or m.after is None:
        return c("changed", color)
    delta = m.after - m.before
    pct = f" ({m.change_pct:+.0f}%)" if m.change_pct is not None else ""
    if delta == int(delta) and m.unit in ("bytes", "", "days"):
        return c(
            f"{delta:+,.0f}{pct}  {_ARROW[m.verdict]}", color, BOLD if m.verdict == "worse" else ""
        )
    return c(
        f"{delta:+,.2f}{pct}  {_ARROW[m.verdict]}", color, BOLD if m.verdict == "worse" else ""
    )


def print_result(result) -> None:
    print(section_header(f"DIFF  {result.kind}", "⇄"))
    print(kv("Before", c(result.before, BWHITE)))
    print(kv("After", c(result.after, BWHITE)))
    print()
    if result.error:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
        print()
        return
    if result.metrics:
        rows = [
            [m.label, _value(m.before, m.unit), _value(m.after, m.unit), _change(m)]
            for m in result.metrics
        ]
        print_table(["Metric", "Before", "After", "Change"], rows)
        print()
    if result.changes:
        print(c("  Changes:", BRAND_SLATE, BOLD))
        for line in result.changes:
            color = BRAND_ROSE if line in result.regressions else BRAND_AMBER
            print(c(f"    {line}", color))
        print()
    if not result.metrics and not result.changes:
        print(c("  No differences.", BRAND_MINT, BOLD))
    elif result.max_regression is not None:
        if result.regressions:
            print(
                c(
                    f"  ✘ {len(result.regressions)} regression(s) beyond {result.max_regression:g}%: ",
                    BRAND_ROSE,
                    BOLD,
                )
                + c(", ".join(result.regressions), BRAND_ROSE)
            )
        else:
            print(c(f"  ✔ No regression beyond {result.max_regression:g}%", BRAND_MINT, BOLD))
    else:
        print(c(f"  {result.better} better · {result.worse} worse", BWHITE))
    print()
