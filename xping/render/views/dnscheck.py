"""DNS health check result rendering."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_INDIGO, BRAND_MINT, BRAND_ROSE, BWHITE, BYELLOW, DIM, c

_GRADE_COLOR = {
    "Excellent": BRAND_MINT,
    "Good": BRAND_MINT,
    "Fair": BYELLOW,
    "Poor": BRAND_AMBER,
    "Critical": BRAND_ROSE,
}
_STATUS_ICON = {
    "ok": c(" ✔ ", BRAND_MINT, BOLD),
    "warn": c(" ⚠ ", BRAND_AMBER, BOLD),
    "fail": c(" ✘ ", BRAND_ROSE, BOLD),
    "info": c(" ℹ ", BRAND_INDIGO),
}
_STATUS_COLOR = {
    "ok": BWHITE,
    "warn": BRAND_AMBER,
    "fail": BRAND_ROSE,
    "info": DIM,
}


def _score_bar(score: int, grade: str, width: int = 36) -> str:
    filled = round(score / 100 * width)
    color = _GRADE_COLOR.get(grade, BWHITE)
    return c("█" * filled, color) + c("░" * (width - filled), DIM)


def print_result(result) -> None:
    color = _GRADE_COLOR.get(result.grade, BWHITE)
    print(c("  " + "─" * 60, DIM))
    print()
    print(
        f"  {c(str(result.score), color, BOLD)}{c('/100', DIM)}   "
        f"{c(result.grade.upper(), color, BOLD)}"
    )
    print(f"  {_score_bar(result.score, result.grade)}")
    print()
    for item in result.checks:
        icon = _STATUS_ICON.get(item.status, " ? ")
        name = c(f"{item.name:<22}", BWHITE, BOLD)
        detail = c(item.detail, _STATUS_COLOR.get(item.status, DIM))
        print(f"  {icon} {name}  {detail}")
    print()
    ok_s = c(f"✔ {result.ok_count} passed", BRAND_MINT)
    warn_s = c(f"⚠ {result.warn_count} warnings", BRAND_AMBER)
    fail_s = c(f"✘ {result.fail_count} failed", BRAND_ROSE if result.fail_count else DIM)
    print(f"  {ok_s}   {warn_s}   {fail_s}")
    print()
