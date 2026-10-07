"""xping report as one self-contained HTML page (inline CSS and SVG, no
scripts, nothing fetched from the network). Every value that came from a
result or a file name is HTML-escaped."""

from __future__ import annotations

import html
import time

from xping import __version__
from xping.models.report import ReportResult, ReportSeries

WIDTH, HEIGHT = 720, 170  # chart viewBox
PAD_L, PAD_R, PAD_T, PAD_B = 56, 12, 12, 28


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _when(ts: float | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return time.strftime(fmt, time.localtime(ts)) if ts is not None else "–"


def _duration(seconds: float) -> str:
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


def _value(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit == "ms":
        return f"{value:.1f} ms"
    text = f"{value:.1f}" if value != int(value) else f"{value:.0f}"
    return f"{text} {unit}".strip()


def _gap_threshold(points) -> float:
    """Seconds between two runs above which the chart line is broken: three
    times the usual interval (the median), so a stopped monitor shows as a
    gap rather than as a straight line through time nobody measured."""
    steps = sorted(b.ts - a.ts for a, b in zip(points, points[1:], strict=False))
    if not steps:
        return float("inf")
    return 3 * max(steps[len(steps) // 2], 1.0)


def _chart(series: ReportSeries) -> str:
    """Line chart of the headline metric; failed runs as red ticks."""
    points = series.points
    if len(points) < 2:
        return '<p class="muted">Not enough runs for a chart yet.</p>'
    t0, t1 = points[0].ts, points[-1].ts
    span = (t1 - t0) or 1.0
    values = series.values
    lo, hi = (min(values), max(values)) if values else (0.0, 1.0)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    plot_w, plot_h = WIDTH - PAD_L - PAD_R, HEIGHT - PAD_T - PAD_B

    def x(ts: float) -> float:
        return PAD_L + (ts - t0) / span * plot_w

    def y(v: float) -> float:
        return PAD_T + (1 - (v - lo) / (hi - lo)) * plot_h

    parts = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="{_e(series.metric or "state")} over time">',
        f'<line class="axis" x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{WIDTH - PAD_R}" '
        f'y2="{PAD_T + plot_h}"/>',
    ]
    for o in series.outages:
        end = o.end if o.end is not None else t1
        parts.append(
            f'<rect class="outage" x="{x(o.start):.1f}" y="{PAD_T}" '
            f'width="{max(2.0, x(end) - x(o.start)):.1f}" height="{plot_h}"/>'
        )
    if values:
        # break the line where a run has no value (a failure), and across
        # gaps with no runs at all (nothing was measuring then)
        gap = _gap_threshold(points)
        segments: list[list[str]] = [[]]
        previous_ts: float | None = None
        for p in points:
            if previous_ts is not None and p.ts - previous_ts > gap and segments[-1]:
                segments.append([])
            previous_ts = p.ts
            if p.value is None:
                if segments[-1]:
                    segments.append([])
                continue
            segments[-1].append(f"{x(p.ts):.1f},{y(p.value):.1f}")
        for seg in segments:
            if len(seg) > 1:
                parts.append(f'<polyline class="line" points="{" ".join(seg)}"/>')
            elif seg:
                cx, cy = seg[0].split(",")
                parts.append(f'<circle class="dot" cx="{cx}" cy="{cy}" r="2"/>')
        unit = f" {series.unit}" if series.unit else ""
        parts.append(
            f'<text class="tick" x="{PAD_L - 6}" y="{PAD_T + 4}" text-anchor="end">'
            f"{_e(f'{hi:.4g}{unit}')}</text>"
        )
        parts.append(
            f'<text class="tick" x="{PAD_L - 6}" y="{PAD_T + plot_h}" text-anchor="end">'
            f"{_e(f'{lo:.4g}{unit}')}</text>"
        )
    for p in points:
        if not p.ok:
            parts.append(
                f'<line class="fail" x1="{x(p.ts):.1f}" y1="{PAD_T + plot_h - 8}" '
                f'x2="{x(p.ts):.1f}" y2="{PAD_T + plot_h}"/>'
            )
    parts.append(
        f'<text class="tick" x="{PAD_L}" y="{HEIGHT - 8}">{_e(_when(t0))}</text>'
        f'<text class="tick" x="{WIDTH - PAD_R}" y="{HEIGHT - 8}" text-anchor="end">'
        f"{_e(_when(t1))}</text></svg>"
    )
    return "".join(parts)


def _state(ok: bool | None) -> str:
    if ok is None:
        return '<span class="badge">–</span>'
    return '<span class="badge up">UP</span>' if ok else '<span class="badge down">DOWN</span>'


def _anchor(series: ReportSeries) -> str:
    raw = f"{series.command}-{series.target}"
    return "s-" + "".join(ch if ch.isalnum() else "-" for ch in raw)[:80]


def _section(series: ReportSeries, now: float) -> str:
    up = f"{series.up_pct:.2f}%" if series.up_pct is not None else "–"
    total_down = sum(
        (o.end if o.end is not None else series.points[-1].ts) - o.start for o in series.outages
    )
    stats = [
        ("State", _state(series.last_ok)),
        ("Uptime", _e(up)),
        ("Runs", _e(series.runs)),
        ("Outages", _e(len(series.outages))),
        ("Downtime", _e(_duration(total_down) if series.outages else "–")),
        (f"Latest {series.metric or ''}".strip(), _e(_value(series.latest, series.unit))),
        ("Median", _e(_value(series.median, series.unit))),
        ("Last run", _e(_when(series.points[-1].ts))),
    ]
    stat_html = "".join(
        f'<div class="stat"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v in stats
    )
    rows = "".join(
        f"<tr><td>{_e(_when(o.start, '%Y-%m-%d %H:%M:%S'))}</td>"
        f"<td>{_e(_when(o.end, '%Y-%m-%d %H:%M:%S')) if o.end else 'still down'}</td>"
        f"<td>{_e(_duration((o.end or now) - o.start))}</td></tr>"
        for o in reversed(series.outages[-20:])
    )
    outage_html = (
        "<table><thead><tr><th>Down from</th><th>Back at</th><th>Lasted</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        if series.outages
        else '<p class="muted">No outages in this period.</p>'
    )
    more = len(series.outages) - 20
    if more > 0:
        outage_html += f'<p class="muted">…and {more} earlier outage(s).</p>'
    return (
        f'<section id="{_anchor(series)}"><h2><span class="cmd">{_e(series.command)}</span> '
        f'{_e(series.target)}</h2><div class="stats">{stat_html}</div>'
        f'<div class="chart">{_chart(series)}</div><h3>Outages</h3>{outage_html}</section>'
    )


_CSS = """
:root{--bg:#f7f8fb;--card:#fff;--fg:#1d2330;--muted:#677089;--line:#dfe3ec;
--accent:#0a9e8f;--up:#13895a;--down:#d0334f;--down-bg:rgba(208,51,79,.10);--chip:#eef1f6}
@media (prefers-color-scheme:dark){:root{--bg:#11141b;--card:#181c25;--fg:#e6e9f0;
--muted:#9aa3b8;--line:#2a3040;--accent:#22d3c0;--up:#4ade80;--down:#ff6b81;
--down-bg:rgba(255,107,129,.14);--chip:#222838}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:0 0 12px;word-break:break-all}
h3{font-size:14px;margin:18px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.muted{color:var(--muted)}section{background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:18px;margin:18px 0}
.cmd{background:var(--chip);border-radius:6px;padding:1px 8px;font-size:14px;color:var(--accent)}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px}
.stat .k{font-size:12px;color:var(--muted)}.stat .v{font-size:17px;font-weight:600}
.chart{margin-top:14px}svg{width:100%;height:auto;display:block}.scroll{overflow-x:auto}
.axis{stroke:var(--line)}.line{fill:none;stroke:var(--accent);stroke-width:1.8;
stroke-linejoin:round}.dot{fill:var(--accent)}.fail{stroke:var(--down);stroke-width:2}
.outage{fill:var(--down-bg)}.tick{fill:var(--muted);font-size:11px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;
padding:6px 8px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600}
.overview td:first-child a{color:var(--fg);word-break:break-all}
@media (max-width:520px){section{padding:14px}th,td{padding:6px 5px}}
.badge{display:inline-block;border-radius:6px;padding:0 8px;font-size:13px;font-weight:700;
background:var(--chip)}.badge.up{color:var(--up)}.badge.down{color:var(--down)}
footer{color:var(--muted);font-size:13px;margin-top:24px}
"""


def to_html(result: ReportResult, title: str = "xping report") -> str:
    now = result.generated
    period = f"since {_when(result.since)}" if result.since else "all saved runs"
    overview_rows = "".join(
        f'<tr><td><a href="#{_anchor(s)}">{_e(s.command)} {_e(s.target)}</a></td>'
        f"<td>{_state(s.last_ok)}</td>"
        f"<td>{_e(f'{s.up_pct:.2f}%' if s.up_pct is not None else '–')}</td>"
        f"<td>{_e(len(s.outages))}</td><td>{_e(_value(s.latest, s.unit))}</td></tr>"
        for s in result.series
    )
    overview = (
        '<section class="scroll"><table class="overview"><thead><tr><th>Target</th><th>State</th>'
        "<th>Uptime</th><th>Outages</th><th>Latest</th></tr></thead>"
        f"<tbody>{overview_rows}</tbody></table></section>"
    )
    sections = "".join(_section(s, now) for s in result.series)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body><main>"
        f'<h1>{_e(title)}</h1><p class="muted">{_e(len(result.series))} target(s), '
        f"{_e(result.runs)} runs, {_e(period)}. Generated {_e(_when(now))}.</p>"
        f"{overview}{sections}"
        f"<footer>Made with xping {_e(__version__)} from the history saved with "
        "<code>--save</code>. Outages run from the first failed check to the first good "
        "one.</footer></main></body></html>\n"
    )
