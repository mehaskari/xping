"""
xping.diagnostics.monitor_state — what ``xping monitor --resume`` keeps
between runs: the totals, state and latest runs of each check.

One JSON file per monitored source under ~/.xping/monitor/, replaced in one
step so a crash cannot leave half a file. A file that cannot be read only
means starting from zero.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from xping.models.monitor import MonitoredCheck

STATE_DIR = Path.home() / ".xping" / "monitor"
VERSION = 1


def state_path(source: str, base: Path | None = None) -> Path:
    """The file of a monitored source (a check file or a list of targets)."""
    return (base or STATE_DIR) / f"{hashlib.sha256(source.encode()).hexdigest()[:16]}.json"


def key(check: MonitoredCheck) -> str:
    """A check is the same one while its name, type and target stay."""
    return "\0".join((check.name, check.type, check.target))


def load(path: Path) -> dict[str, dict]:
    """The saved checks by key; empty when there is nothing usable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return {}
    checks = data.get("checks")
    return checks if isinstance(checks, dict) else {}


def save(path: Path, checks: list[MonitoredCheck]) -> None:
    """Replace the file; raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"version": VERSION, "checks": {key(c): c.export_state() for c in checks}}
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump(body, file)
    os.replace(temporary, path)
