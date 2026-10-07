"""xping monitor rendering: the live table, change lines and the summary."""

from __future__ import annotations

import time
from pathlib import Path

from ..animations import fit
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
    pad,
    safe,
    visible_len,
)
from ..layout import kv, section_header, terminal_width
from ..progress import clear_lines
from ..tables import print_table

TREND = 16  # samples shown in the trend column
_MIN_DETAIL = 12  # keep at least this much room for the detail column
_MIN_NAME = 12  # check names are never cut shorter than this
_BLOCKS = "▁▂▃▄▅▆▇█"


def duration(seconds: float) -> str:
    """12s, 4m05s, 2h03m, 3d04h; a zero remainder is left out (1m, 2h, 1d)."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h" if hours else f"{days}d"


def value_text(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit == "ms":
        return f"{value:.1f} ms"
    number = f"{value:.1f}" if abs(value) < 100 and value != int(value) else f"{value:.0f}"
    return f"{number} {unit}".strip()


def trend(check) -> str:
    """Last TREND runs: a bar per value (scaled to the window), × for a
    failure, ▪ for a pass without a number."""
    samples = check.samples[-TREND:]
    values = [s.value for s in samples if s.ok and s.value is not None]
    lo, hi = (min(values), max(values)) if values else (0.0, 0.0)
    out = []
    for s in samples:
        if not s.ok:
            out.append(c("×", BRAND_ROSE, BOLD))
        elif s.value is None:
            out.append(c("▪", BRAND_MINT))
        else:
            level = 0 if hi == lo else round((s.value - lo) / (hi - lo) * (len(_BLOCKS) - 1))
            out.append(c(_BLOCKS[level], BRAND_MINT))
    return "".join(out)


def _state(check) -> str:
    """The confirmed state; ◐ while the latest runs disagree with it (a
    failure not yet confirmed by fail_after, or a recovery by recover_after)."""
    if check.up is None:
        return c("○ wait", DIM)
    unsure = check.last_ok is not None and check.last_ok != check.up
    mark = "◐" if unsure else "●"
    if check.up:
        return c(f"{mark} UP  ", BRAND_AMBER if unsure else BRAND_MINT, BOLD)
    return c(f"{mark} DOWN", BRAND_AMBER if unsure else BRAND_ROSE, BOLD)


def _every_text(result) -> str:
    values = sorted({k.every for k in result.checks})
    if not values:
        return "–"
    if len(values) == 1:
        return duration(values[0])
    return f"{duration(values[0])} – {duration(values[-1])}"


def print_header(result) -> None:
    print(section_header(f"MONITOR  {Path(result.source).name}", "◉"))
    print(kv("Checks", str(len(result.checks))))
    print(kv("Every", _every_text(result)))
    print(kv("Stop", "Ctrl-C"))
    print()


def live_lines(result, now: float, width: int | None = None) -> list[str]:
    """The live table as lines, each at most *width* - 1 columns wide (a
    line that wraps would break the in-place redraw)."""
    width = (width or terminal_width()) - 1
    checks = result.checks
    headers = ["State", "Check", "Type", "Target", "Now", "Trend", "Up", "For"]
    rows = []
    for k in checks:
        uptime = f"{k.up_pct:.0f}%" if k.up_pct is not None else "–"
        rows.append(
            [
                _state(k),
                c(safe(k.name), BWHITE, BOLD),
                k.type,
                c(safe(k.target), DIM),
                value_text(k.latest, k.unit),
                trend(k),
                uptime,
                duration(now - k.since) if k.since is not None else "–",
            ]
        )
    widths = [
        max(len(h), max((visible_len(r[i]) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]
    widths[1] = min(widths[1], 24)
    widths[3] = min(widths[3], 32)
    # On a narrow terminal, drop the least important columns rather than
    # cutting off the uptime: Type first, then Target, Trend and For.
    shown = list(range(len(headers)))

    def room() -> int:  # columns left for the detail
        return width - 2 - sum(widths[i] + 2 for i in shown)

    for column in (2, 3, 5, 7):
        if room() >= _MIN_DETAIL:
            break
        shown.remove(column)
    # still too narrow: shorten the check names, and if even that is not
    # enough, leave the detail out rather than show a couple of letters
    if room() < _MIN_DETAIL:
        widths[1] = max(_MIN_NAME, widths[1] - (_MIN_DETAIL - room()))
    with_detail = room() >= _MIN_DETAIL

    def line(cells: list[str], detail: str) -> str:
        parts = [pad(fit(cells[i], widths[i]), widths[i]) for i in shown]
        text = "  " + "  ".join(parts)
        if detail and with_detail:
            text += "  " + detail
        return fit(text.rstrip(), width)

    lines = [line([c(h, BRAND_INDIGO, BOLD) for h in headers], c("Detail", BRAND_INDIGO, BOLD))]
    for k, row in zip(checks, rows, strict=True):
        colour = DIM if k.last_ok else BRAND_ROSE
        lines.append(line(row, c(safe(k.detail), colour) if k.detail else ""))
    up = sum(1 for k in checks if k.up)
    down = sum(1 for k in checks if k.up is False)
    footer = c(f"  {up} up", BRAND_MINT, BOLD) + c("  ·  ", DIM)
    footer += c(f"{down} down", BRAND_ROSE, BOLD) if down else c("0 down", DIM)
    footer += c(f"  ·  running {duration(now - result.started)}", DIM)
    footer += c(f"  ·  {time.strftime('%H:%M:%S', time.localtime(now))}", DIM)
    lines += ["", fit(footer, width)]
    return lines


def redraw(result, now: float, printed: int = 0) -> int:
    """Redraw the live table in place; returns the number of lines printed."""
    if printed:
        clear_lines(printed)
    lines = live_lines(result, now)
    print("\n".join(lines), flush=True)
    return len(lines)


def change_widths(result) -> tuple[int, int]:
    """(name, type) column widths for print_change, so every line of a log
    lines up; names are capped so one long name cannot push the rest away."""
    names = [visible_len(safe(k.name)) for k in result.checks] or [0]
    types = [len(k.type) for k in result.checks] or [0]
    return min(max(names), 32), max(types)


def print_change(
    check,
    ts: float,
    previous: bool | None,
    previous_since: float | None = None,
    widths: tuple[int, int] = (0, 0),
) -> None:
    """One line per confirmed state change, for output that is not a terminal.
    *widths* (see change_widths) pads the name and type columns."""
    clock = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    if check.up:
        state = c("UP  ", BRAND_MINT, BOLD)
    else:
        state = c("DOWN", BRAND_ROSE, BOLD)
    note = ""
    if previous is False and previous_since is not None and check.since is not None:
        # back up: the outage lasted from its first failure to the first good run
        note = c(f"  (down for {duration(check.since - previous_since)})", DIM)
    name_w, type_w = widths
    name = c(safe(check.name), BWHITE, BOLD)
    if name_w:
        name = pad(fit(name, name_w), name_w)
    kind = pad(c(check.type, BRAND_SLATE), type_w)
    detail = c(safe(check.detail), DIM if check.up else BRAND_ROSE)
    print(f"  {c(clock, DIM)}  {state}  {name}  {kind}  {detail}{note}")


def print_summary(result) -> None:
    ended = result.ended or time.time()
    print()
    print(section_header("MONITOR SUMMARY", "◉"))
    print(kv("Ran for", duration(ended - result.started)))
    print()
    rows = []
    for k in result.checks:
        rows.append(
            [
                _state(k),
                k.name,
                k.type,
                k.target,
                f"{k.up_pct:.1f}%" if k.up_pct is not None else "–",
                str(k.checks),
                str(k.outages),
                duration(k.longest_outage_s) if k.outages else "–",
                value_text(k.average, k.unit) if k.metric else "–",
            ]
        )
    print_table(
        ["State", "Check", "Type", "Target", "Uptime", "Runs", "Outages", "Longest", "Average"],
        rows,
    )
    print()
    total = len(result.checks)
    if result.ok:
        print(c(f"  ✔ All {total} checks up at the end", BRAND_MINT, BOLD))
    else:
        down = ", ".join(result.down)
        print(c(f"  ✘ {len(result.down)} of {total} down at the end: {down}", BRAND_ROSE, BOLD))
    if any(k.outages for k in result.checks):
        print(c("  Outages are counted from the first failed run to the next good one.", DIM))
    print()
