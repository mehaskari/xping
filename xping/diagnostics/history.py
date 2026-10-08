"""
xping.diagnostics.history — keep results over time, and read them back.

Runs are recorded only when asked: ``--save`` on a measurement command, or
``save = true`` in the config file's [defaults]. Each (command, target)
pair gets one JSON-lines file under ~/.xping/history/<command>/, one line
per run: {"ts": unix time, "ok": verdict, "target": …, "result": {…}}.
The newest MAX_RUNS runs are kept.

`xping history` lists what is recorded; `xping history ping example.net`
shows the runs as a table with the command's key metrics, a trend line,
and how the latest run compares with the usual (median) value.
"""

from __future__ import annotations

import json
import re
import shutil
import statistics
import time
from pathlib import Path
from typing import Any

from xping.diagnostics.diff import METRICS, _get, _number
from xping.models.history import HistoryEntry, HistoryResult, HistoryRun

HISTORY_DIR = Path.home() / ".xping" / "history"
MAX_RUNS = 500
SHOWN_METRICS = 3

# command -> how to name the target from its parsed arguments
TARGETS = {
    "ping": lambda a: a.host,
    "trace": lambda a: a.host,
    "mtr": lambda a: a.host,
    "health": lambda a: a.host,
    "tls": lambda a: f"{a.host}:{a.port}" if a.port != 443 else a.host,
    "tcp": lambda a: f"{a.host}:{a.port}",
    "udp": lambda a: f"{a.host}:{a.port}",
    "http": lambda a: a.url,
    "smtp": lambda a: f"{a.host}:{a.port}" if a.port != 25 else a.host,
    "dnscheck": lambda a: a.domain,
    "blocklist": lambda a: a.target,
    "ntp": lambda a: a.server,
    "speedtest": lambda a: "cloudflare",
    "wifi": lambda a: a.interface or "default",
    "doctor": lambda a: a.host or "internet",
    "check": lambda a: str(Path(a.file).resolve()),
}
# The metrics worth following over time, where they differ from the first
# three diff compares (for ping, loss and jitter matter more than min/max)
_FOLLOW = {
    "ping": ("Average RTT", "Jitter", "Packet loss"),
    "health": ("Health score", "Average RTT", "Packet loss"),
    "http": ("Total time", "Server response", "TLS handshake"),
    "mtr": ("Destination avg RTT", "Destination loss"),
    "wifi": ("Signal", "SNR", "Link rate"),
}


def _slug(target: str) -> str:
    """A safe, readable file name for any target (URLs, IPv6, ports)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", target).strip("_")[:120] or "_"


def _file(command: str, target: str, base: Path | None = None) -> Path:
    return (base or HISTORY_DIR) / command / f"{_slug(target)}.jsonl"


def result_data(result: object) -> Any:
    """A result as stored: its dict, or a list of dicts for trace hops."""
    if isinstance(result, list):
        return [item.to_dict() for item in result]
    return result.to_dict()  # type: ignore[attr-defined]  # every result model has it


def followed_metrics(command: str) -> list:
    """The metrics history follows for *command*, headline first."""
    known = METRICS.get(command, ())
    wanted = _FOLLOW.get(command)
    return [m for m in known if m.label in wanted] if wanted else list(known[:SHOWN_METRICS])


def headline(command: str, result: object):
    """(metric, value) of the number most worth following for *result*,
    e.g. ("Average RTT", 12.3); (None, None) when the type has none."""
    metrics = followed_metrics(command)
    if not metrics:
        return None, None
    return metrics[0], _number(_get(result_data(result), metrics[0].path))


def record(command: str, target: str, result: object, ok: bool, base: Path | None = None) -> Path:
    """Append one run; trim the file to the newest MAX_RUNS runs."""
    data = result_data(result)
    path = _file(command, target, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": time.time(), "ok": ok, "target": target, "result": data})
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > MAX_RUNS:
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines[-MAX_RUNS:]) + "\n", encoding="utf-8")
        tmp.replace(path)
    return path


def _read(path: Path) -> list[dict]:
    runs: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return runs
    for line in text.splitlines():
        try:
            run = json.loads(line)
        except json.JSONDecodeError:
            continue  # a half-written line never breaks the history
        if isinstance(run, dict) and "ts" in run:
            runs.append(run)
    return runs


def entries(base: Path | None = None) -> list[HistoryEntry]:
    """Everything recorded, newest activity first."""
    found: list[HistoryEntry] = []
    root = base or HISTORY_DIR
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*/*.jsonl")):
        runs = _read(path)
        if runs:
            found.append(
                HistoryEntry(
                    command=path.parent.name,
                    target=runs[-1].get("target", path.stem),
                    runs=len(runs),
                    first=runs[0]["ts"],
                    last=runs[-1]["ts"],
                )
            )
    return sorted(found, key=lambda e: e.last, reverse=True)


def parse_since(value: str) -> float:
    """ "30m", "12h", "7d", "2w" -> seconds."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([mhdw])\s*", value.lower())
    if not m:
        raise ValueError("use a number and m, h, d or w, e.g. 12h or 7d")
    return float(m.group(1)) * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[m.group(2)]


def show(
    command: str,
    target: str,
    last: int | None = None,
    since: float | None = None,
    base: Path | None = None,
    now: float | None = None,
) -> HistoryResult:
    result = HistoryResult(command=command, target=target)
    runs = _read(_file(command, target, base))
    if not runs:
        result.error = f"no saved runs for {command} {target} (record some with --save)"
        return result
    if since is not None:
        cutoff = (now or time.time()) - since
        runs = [r for r in runs if r["ts"] >= cutoff]
    if last:
        runs = runs[-last:]
    metrics = followed_metrics(command)
    result.metrics = [m.label for m in metrics]
    result.units = {m.label: m.unit for m in metrics}
    for run in runs:
        values = {m.label: _number(_get(run.get("result"), m.path)) for m in metrics}
        result.runs.append(HistoryRun(ts=run["ts"], ok=bool(run.get("ok")), values=values))
    if len(result.runs) >= 3 and result.metrics:
        headline = result.metrics[0]
        earlier = [v for r in result.runs[:-1] if (v := r.values[headline]) is not None]
        latest = result.runs[-1].values[headline]
        if earlier and latest is not None:
            result.median = statistics.median(earlier)
            if result.median:
                result.latest_vs_median_pct = (latest - result.median) / abs(result.median) * 100
    return result


def prune(
    older_than: float,
    command: str | None = None,
    target: str | None = None,
    base: Path | None = None,
    now: float | None = None,
) -> int:
    """Drop runs older than *older_than* seconds (all, one command, or one
    command and target); returns how many runs were removed. Files left
    without runs are deleted."""
    root = base or HISTORY_DIR
    if command and target:
        files = [_file(command, target, base)]
    else:
        folder = root / command if command else root
        files = sorted(folder.rglob("*.jsonl")) if folder.is_dir() else []
    cutoff = (now if now is not None else time.time()) - older_than
    removed = 0
    for path in files:
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        kept = []
        for line in lines:
            try:
                ts = json.loads(line).get("ts", 0)
            except (json.JSONDecodeError, AttributeError):
                ts = 0  # unreadable lines are dropped too
            if isinstance(ts, (int, float)) and ts >= cutoff:
                kept.append(line)
        if len(kept) == len(lines):
            continue
        removed += len(lines) - len(kept)
        if kept:
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
            tmp.replace(path)
        else:
            path.unlink()
    return removed


def clear(command: str | None = None, target: str | None = None, base: Path | None = None) -> int:
    """Delete saved runs; returns how many files were removed."""
    root = base or HISTORY_DIR
    if command and target:
        path = _file(command, target, base)
        if path.exists():
            path.unlink()
            return 1
        return 0
    folder = root / command if command else root
    if not folder.is_dir():
        return 0
    count = sum(1 for _ in folder.rglob("*.jsonl"))
    shutil.rmtree(folder)
    return count
