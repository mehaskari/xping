"""Speed test result rendering."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_INDIGO, BRAND_MINT, BRAND_ROSE, BWHITE, DIM, c
from ..tables import print_table

_GRADE_COLOR = {
    "Excellent": BRAND_MINT,
    "Good":      BRAND_MINT,
    "Fair":      BRAND_AMBER,
    "Poor":      BRAND_ROSE,
    "Critical":  BRAND_ROSE,
    "Unknown":   DIM,
}

def _speed_bar(mbps: float, max_mbps: float = 200.0, width: int = 36) -> str:
    filled = min(int(mbps / max_mbps * width), width)
    color = (BRAND_MINT if mbps >= 25 else BRAND_AMBER if mbps >= 5 else BRAND_ROSE)
    return c("█" * filled, color) + c("░" * (width - filled), DIM)


def print_result(result) -> None:
    grade = result.grade
    color = _GRADE_COLOR.get(grade, BWHITE)
    print()
    print(c("  " + "─" * 60, DIM))
    print()

    if result.download_mbps is not None:
        print(f"  {c('Download', BRAND_INDIGO, BOLD)}")
        print(f"  {_speed_bar(result.download_mbps)}")
        print(f"  {c(f'{result.download_mbps:.1f} Mbps', color, BOLD)}  "
              f"{c(grade.upper(), color)}")
        print()

    rows = []
    if result.ping_ms is not None:
        rows.append(["Ping", f"{result.ping_ms:.1f} ms"])
    if result.download_mbps is not None:
        rows.append(["Download", f"{result.download_mbps:.1f} Mbps"])
    if result.upload_mbps is not None:
        rows.append(["Upload", f"{result.upload_mbps:.1f} Mbps"])
    if result.server:
        rows.append(["Server", result.server])
    if rows:
        print_table(["Metric", "Value"], rows)
    print()

    # Speed context
    contexts = [
        (1,   "Streaming HD video (1 Mbps)"),
        (5,   "Streaming 4K video (5 Mbps)"),
        (25,  "Fast browsing & conferencing (25 Mbps)"),
        (100, "Heavy use / multiple users (100 Mbps)"),
    ]
    if result.download_mbps is not None:
        dl = result.download_mbps
        passed = [label for thresh, label in contexts if dl >= thresh]
        if passed:
            print(c("  ✔  Enough for:", BRAND_MINT, BOLD))
            for label in passed:
                print(c(f"     {label}", DIM))
            print()
