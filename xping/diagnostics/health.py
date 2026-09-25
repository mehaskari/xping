"""
xping.diagnostics.health — Network Health Score.
Combines DNS resolve time, packet loss, latency, and jitter into a single
actionable 0-100 score with a human-readable summary of what's wrong.
Score history is persisted in ~/.xping/health_history.json.
"""

import json
import socket
import time
from pathlib import Path

from xping.diagnostics.ping import ping
from xping.diagnostics.resolve import resolve
from xping.models.health import HealthResult
from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header
from xping.render.errors import resolve_error
from xping.render.views import health as health_view

_HISTORY_FILE = Path.home() / ".xping" / "health_history.json"
_MAX_HISTORY = 50  # entries per host


def _load_history(host: str) -> list[dict]:
    try:
        data = json.loads(_HISTORY_FILE.read_text())
        return data.get(host, [])
    except Exception:
        return []


def _save_history(host: str, score: int, grade: str) -> list[dict]:
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(_HISTORY_FILE.read_text())
        except Exception:
            data = {}
        entry = {
            "ts": int(time.time()),
            "score": score,
            "grade": grade,
        }
        data.setdefault(host, []).append(entry)
        data[host] = data[host][-_MAX_HISTORY:]
        tmp = _HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(_HISTORY_FILE)
        return data[host]
    except Exception:
        return []


def _score(dns_ms: float, ping_result) -> tuple[int, list[str]]:
    """Derive a 0-100 score and a list of actionable findings."""
    if ping_result.loss_pct >= 100:
        return 0, ["Host is completely unreachable — 100% packet loss."]

    score = 100
    issues: list[str] = []

    loss = ping_result.loss_pct
    loss_penalty = min(50, round(loss * 0.6))
    if loss_penalty:
        score -= loss_penalty
        issues.append(f"Packet loss is {loss:.0f}% — expect retransmissions and stalls.")

    avg = ping_result.avg_rtt
    if avg >= 300:
        score -= 25
        issues.append(
            f"Average latency is very high ({avg:.0f} ms) — noticeable lag for any interactive use."
        )
    elif avg >= 100:
        score -= 15
        issues.append(
            f"Average latency is elevated ({avg:.0f} ms) — fine for browsing, rough for gaming or calls."
        )
    elif avg >= 30:
        score -= 5

    jitter = ping_result.jitter
    if jitter >= 80:
        score -= 15
        issues.append(f"Jitter is high ({jitter:.0f} ms) — voice/video calls will sound choppy.")
    elif jitter >= 30:
        score -= 10
        issues.append(f"Jitter is noticeable ({jitter:.0f} ms) — real-time traffic may stutter.")
    elif jitter >= 10:
        score -= 5

    if dns_ms >= 400:
        score -= 10
        issues.append(f"DNS resolution is slow ({dns_ms:.0f} ms) — consider a faster resolver.")
    elif dns_ms >= 150:
        score -= 5

    return max(0, min(100, score)), issues


def health(
    host: str,
    count: int = 8,
    timeout: float = 2.0,
    quiet: bool = False,
    family: int | None = None,
) -> HealthResult:
    """Run DNS + ping diagnostics and roll them up into a health score."""
    result = HealthResult(host=host)

    if not quiet:
        print(section_header(f"NETWORK HEALTH  {host}", "◆"))
        print(kv("Target", c(host, BRAND_TEAL, BOLD)))
        print()

    t0 = time.perf_counter()
    try:
        ip = resolve(host, family)
    except socket.gaierror:
        if not quiet:
            resolve_error(host)
        result.resolved = False
        result.score = 0
        result.issues = ["DNS resolution failed — the host could not be found."]
        return result
    dns_ms = (time.perf_counter() - t0) * 1000

    result.ip = ip
    result.dns_resolve_ms = dns_ms

    if not quiet:
        print(kv("IP", c(ip, BRAND_INDIGO)))
        print(kv("DNS resolve", f"{dns_ms:.1f} ms"))

    ping_result = ping(host=host, count=count, timeout=timeout, quiet=quiet, family=family)
    result.ping = ping_result

    score, issues = _score(dns_ms, ping_result)
    result.score = score
    result.issues = issues

    # persist and attach history
    result.history = _save_history(host, score, result.grade)

    if not quiet:
        health_view.print_summary(result)
    return result
