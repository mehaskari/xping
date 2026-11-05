"""
xping.exporters.status_page — ``xping monitor --status-page``: the monitored
checks as a live web page, for whoever does not want Prometheus and Grafana.

``render()`` writes one self-contained HTML page (inline CSS and SVG, no
scripts, nothing fetched from the network) that reloads itself; ``to_json()``
gives the same state to scripts. Every value that came from a check is
HTML-escaped.
"""

from __future__ import annotations

import json
import time

from xping import __version__
from xping.exporters.html_report import _duration, _e, _value, _when
from xping.models.monitor import MonitoredCheck, MonitorResult

HTML_TYPE = "text/html; charset=utf-8"
JSON_TYPE = "application/json; charset=utf-8"
REFRESH = 10  # seconds between reloads of the page
BARS = 48  # runs drawn per check
OUTAGES = 10  # recent outages listed

_CSS = """
:root{color-scheme:light dark;--bg:#f6f8fa;--card:#fff;--ink:#1a2330;--dim:#5d6b7a;
--line:#dfe5ec;--up:#0a9d7c;--down:#d93a5b;--warn:#b77900;--idle:#9aa7b4}
@media (prefers-color-scheme:dark){:root{--bg:#0a0e12;--card:#12181f;--ink:#eaf1f6;
--dim:#93a1af;--line:#222c36;--up:#00d2be;--down:#ff6b8a;--warn:#ffc35c;--idle:#566472}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 48px}
h1{margin:0;font-size:24px;line-height:1.25}
h2{margin:32px 0 10px;font-size:15px}
.banner{display:flex;gap:14px;align-items:center;padding:18px 20px;border-radius:10px;
background:var(--card);border:1px solid var(--line);border-left:5px solid var(--tone)}
.sub{color:var(--dim);font-size:13px}
.check{padding:14px 20px;background:var(--card);border:1px solid var(--line);
border-radius:10px;margin-top:10px}
.row{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:baseline}
.name{font-weight:600;overflow-wrap:anywhere}
.state{font-size:12px;font-weight:700;letter-spacing:.04em;color:var(--tone)}
.push{margin-left:auto;font-variant-numeric:tabular-nums}
.target{color:var(--dim);font-size:13px;overflow-wrap:anywhere}
.detail{color:var(--dim);font-size:13px;margin-top:2px;overflow-wrap:anywhere}
svg{display:block;width:100%;height:28px;margin-top:10px}
.up{--tone:var(--up)}.down{--tone:var(--down)}.warn{--tone:var(--warn)}.idle{--tone:var(--idle)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}
th,td{padding:8px 12px;text-align:left;border-top:1px solid var(--line);font-size:13px}
th{color:var(--dim);font-weight:600;border-top:0}
footer{margin-top:28px;color:var(--dim);font-size:12px}
footer a{color:inherit}
"""


def _state(check: MonitoredCheck) -> tuple[str, str]:
    """(css class, label): failing is a failed run not yet confirmed as DOWN."""
    if check.up is False:
        return "down", "DOWN"
    if check.last_ok is False:
        return "warn", "FAILING"
    if check.up:
        return "up", "UP"
    return "idle", "WAITING"


def _bars(check: MonitoredCheck) -> str:
    """The latest runs, oldest first: a bar per run, red when it failed."""
    samples = check.samples[-BARS:]
    if not samples:
        return ""
    rects = "".join(
        f'<rect x="{(BARS - len(samples) + i) * 10}" width="7" height="28" rx="2" '
        f'fill="var(--{"up" if s.ok else "down"})"/>'
        for i, s in enumerate(samples)
    )
    return (
        f'<svg viewBox="0 0 {BARS * 10 - 3} 28" preserveAspectRatio="none" role="img" '
        f'aria-label="latest {len(samples)} runs">{rects}</svg>'
    )


def _check(check: MonitoredCheck, now: float) -> str:
    tone, label = _state(check)
    facts = [_value(check.latest, check.unit)] if check.latest is not None else []
    if check.up_pct is not None:
        facts.append(f"{check.up_pct:.2f}% up")
    if check.since is not None:
        facts.append(f"for {_duration(now - check.since)}")
    detail = f'<div class="detail">{_e(check.detail)}</div>' if check.detail else ""
    return (
        f'<section class="check {tone}"><div class="row">'
        f'<span class="name">{_e(check.name)}</span><span class="state">{label}</span>'
        f'<span class="push sub">{_e(" · ".join(facts))}</span></div>'
        f'<div class="target">{_e(check.type)} · {_e(check.target)}</div>'
        f"{detail}{_bars(check)}</section>"
    )


def _outages(result: MonitorResult, now: float) -> str:
    spans = [(start, end, c.name) for c in result.checks for start, end in c.outage_spans]
    if not spans:
        return ""
    spans.sort(key=lambda span: span[0], reverse=True)
    rows = "".join(
        f"<tr><td>{_e(name)}</td><td>{_when(start)}</td>"
        f"<td>{_duration((now if end is None else end) - start)}"
        f"{' so far' if end is None else ''}</td></tr>"
        for start, end, name in spans[:OUTAGES]
    )
    return (
        "<h2>Recent outages</h2><table><thead><tr><th>Check</th><th>Began</th>"
        f"<th>Lasted</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def _banner(result: MonitorResult) -> tuple[str, str]:
    down = len(result.down)
    if down:
        return "down", f"{down} of {len(result.checks)} checks down"
    if any(c.last_ok is False for c in result.checks):
        return "warn", "Some checks are failing"
    if all(c.up for c in result.checks):
        return "up", "All checks up"
    return "idle", "Waiting for the first runs"


def render(result: MonitorResult, now: float | None = None) -> str:
    """The state of the monitor (a MonitorResult) as a page that reloads itself."""
    now = time.time() if now is None else now
    tone, headline = _banner(result)
    checks = "".join(_check(c, now) for c in result.checks)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="{REFRESH}">'
        f"<title>{_e(headline)} · xping</title><style>{_CSS}</style></head><body><main>"
        f'<div class="banner {tone}"><div><h1>{_e(headline)}</h1>'
        f'<div class="sub">Checked {_when(now, "%Y-%m-%d %H:%M:%S")}, '
        f"running for {_duration(now - result.started)}</div></div></div>"
        f"{checks}{_outages(result, now)}"
        f'<footer>xping {_e(__version__)} · <a href="/status.json">JSON</a> · '
        '<a href="/metrics">Prometheus metrics</a></footer></main></body></html>\n'
    )


def to_json(result: MonitorResult, now: float | None = None) -> str:
    """The same state for scripts, without the samples of every run."""
    now = time.time() if now is None else now
    checks = [
        {
            "name": c.name,
            "type": c.type,
            "target": c.target,
            "state": _state(c)[1].lower(),
            "since": c.since,
            "detail": c.detail,
            "metric": c.metric,
            "unit": c.unit,
            "latest": c.latest,
            "average": c.average,
            "up_pct": c.up_pct,
            "runs": c.checks,
            "failures": c.failures,
            "outages": c.outages,
            "every": c.every,
        }
        for c in result.checks
    ]
    state = {
        "ok": result.ok,
        "started": result.started,
        "time": now,
        "version": __version__,
        "checks": checks,
    }
    return json.dumps(state, ensure_ascii=False, indent=2) + "\n"
