"""Speed test result rendering."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_INDIGO, BRAND_MINT, BRAND_ROSE, BWHITE, DIM, c
from ..tables import print_table

_GRADE_COLOR = {
    "Excellent": BRAND_MINT,
    "Good": BRAND_MINT,
    "Fair": BRAND_AMBER,
    "Poor": BRAND_ROSE,
    "Critical": BRAND_ROSE,
    "Unknown": DIM,
}


def _speed_bar(mbps: float, max_mbps: float = 200.0, width: int = 36) -> str:
    filled = min(int(mbps / max_mbps * width), width)
    color = BRAND_MINT if mbps >= 25 else BRAND_AMBER if mbps >= 5 else BRAND_ROSE
    return c("█" * filled, color) + c("░" * (width - filled), DIM)


_BLOAT_COLOR = {
    "A+": BRAND_MINT,
    "A": BRAND_MINT,
    "B": BRAND_AMBER,
    "C": BRAND_AMBER,
    "D": BRAND_ROSE,
    "F": BRAND_ROSE,
}
_BLOAT_MEANING = {
    "A+": "latency barely moves under load",
    "A": "fine for calls and gaming while the line is busy",
    "B": "calls and games may stutter during big downloads or uploads",
    "C": "noticeable lag whenever someone downloads or uploads",
    "D": "calls and games break up while the line is busy",
    "F": "the connection is nearly unusable while it is busy",
}


def _print_bufferbloat(result) -> None:
    grade = result.bufferbloat_grade
    if grade is None:
        if result.idle_latency_ms is not None or result.download_latency_ms is not None:
            print(c("  Bufferbloat could not be measured.", DIM))
            print()
        return
    color = _BLOAT_COLOR[grade]
    print(f"  {c('Bufferbloat', BRAND_INDIGO, BOLD)}")
    print(
        f"  {c(f'+{result.bufferbloat_ms:.0f} ms', color, BOLD)} under load"
        f"  {c('GRADE ' + grade, color, BOLD)}  {c(_BLOAT_MEANING[grade], DIM)}"
    )
    if grade not in ("A+", "A"):
        print(
            c(
                "  Turn on SQM / Smart Queue (fq_codel or CAKE) in your router, "
                "set a little below your measured speeds.",
                DIM,
            )
        )
    print()


def print_result(result) -> None:
    grade = result.grade
    color = _GRADE_COLOR.get(grade, BWHITE)
    print()
    if result.error:
        print(c(f"  ✘  {result.error}", BRAND_ROSE, BOLD))
        print()
    print(c("  " + "─" * 60, DIM))
    print()

    if result.download_mbps is not None:
        print(f"  {c('Download', BRAND_INDIGO, BOLD)}")
        print(f"  {_speed_bar(result.download_mbps)}")
        print(f"  {c(f'{result.download_mbps:.1f} Mbps', color, BOLD)}  {c(grade.upper(), color)}")
        print()

    rows = []
    if result.ping_ms is not None:
        rows.append(["Ping", f"{result.ping_ms:.1f} ms"])
    if result.download_mbps is not None:
        rows.append(["Download", f"{result.download_mbps:.1f} Mbps"])
    if result.upload_mbps is not None:
        rows.append(["Upload", f"{result.upload_mbps:.1f} Mbps"])
    for label, value in (
        ("Latency idle", result.idle_latency_ms),
        ("Latency ↓ loaded", result.download_latency_ms),
        ("Latency ↑ loaded", result.upload_latency_ms),
    ):
        if value is not None:
            rows.append([label, f"{value:.1f} ms"])
    if result.server:
        rows.append(["Server", result.server])
    rows.append(["Connections", str(result.connections)])
    if result.download_bytes:
        rows.append(["Data used", f"{(result.download_bytes + result.upload_bytes) / 1e6:.0f} MB"])
    if rows:
        print_table(["Metric", "Value"], rows)
    print()
    _print_bufferbloat(result)

    # Speed context
    contexts = [
        (1, "Streaming HD video (1 Mbps)"),
        (5, "Streaming 4K video (5 Mbps)"),
        (25, "Fast browsing & conferencing (25 Mbps)"),
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
