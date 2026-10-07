"""
xping.diagnostics.report — turn the saved history into one HTML page.

Every command-and-target pair recorded with ``--save`` (or by
``xping monitor --save``) becomes a section: uptime, outages, the latest
and median value of its headline metric, and a chart of that metric over
time with the failed runs marked. The page is a single file with no
scripts and nothing loaded from the network, so it can be mailed,
archived or put on any web server.
"""

from __future__ import annotations

import time
from pathlib import Path

from xping.diagnostics import history
from xping.models.report import ReportOutage, ReportPoint, ReportResult, ReportSeries
from xping.statefilter import outages


def build(
    command: str | None = None,
    target: str | None = None,
    since: float | None = None,
    last: int | None = None,
    base: Path | None = None,
    now: float | None = None,
) -> ReportResult:
    """Collect the history (optionally one command, or one command and
    target) into a ReportResult."""
    now = now if now is not None else time.time()
    result = ReportResult(generated=now, since=(now - since) if since else None)
    pairs = [(e.command, e.target) for e in history.entries(base)]
    if command:
        pairs = [p for p in pairs if p[0] == command]
    if target:
        pairs = [p for p in pairs if p[1] == target]
    for cmd, tgt in sorted(pairs):
        shown = history.show(cmd, tgt, last=last, since=since, base=base, now=now)
        if shown.error or not shown.runs:
            continue
        metric = shown.metrics[0] if shown.metrics else None
        series = ReportSeries(
            command=cmd,
            target=tgt,
            metric=metric,
            unit=shown.units.get(metric, "") if metric else "",
            points=[
                ReportPoint(r.ts, r.ok, r.values.get(metric) if metric else None)
                for r in shown.runs
            ],
        )
        series.outages = [
            ReportOutage(start, end) for start, end in outages((p.ts, p.ok) for p in series.points)
        ]
        result.series.append(series)
    if not result.series:
        what = " ".join(x for x in (command, target) if x)
        if not pairs:
            result.error = f"no saved runs for {what}" if what else "nothing saved yet"
        else:
            result.error = f"no saved runs for {what or 'anything'} in this period"
    return result
