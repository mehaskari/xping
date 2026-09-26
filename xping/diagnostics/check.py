"""
xping.diagnostics.check — run many checks from one config file.

TOML (Python 3.11+) or JSON. Every check runs concurrently and quietly,
and is judged by the same verdicts and thresholds as the single commands,
so a config file is a monitoring script with one exit code.

    [defaults]
    timeout = 3

    [[check]]
    name = "Prod DB"
    type = "tcp"
    host = "prod-db"        # saved profile names work
    port = 5432
    max_latency = 50

JSON uses the same keys: {"defaults": {...}, "checks": [{...}, ...]}.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from xping.cli.verdict import evaluate
from xping.diagnostics import profile as profile_diag
from xping.models.check import CheckOutcome, CheckReport
from xping.render import BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.views import check as check_view

EXAMPLE = """\
# xping check - run with:  xping check checks.toml
# Exit code 0 when every check passes, 1 otherwise.

[defaults]
timeout = 3

[[check]]
name = "Cloudflare DNS reachable"
type = "ping"
host = "1.1.1.1"
count = 4
max_loss = 25
max_latency = 150

[[check]]
name = "Database port"
type = "tcp"
host = "db.example.com"      # or a saved profile name
port = 5432
max_latency = 50

[[check]]
name = "Website"
type = "http"
url = "https://example.com"
expect_status = 200
max_latency = 1500

[[check]]
name = "Certificate"
type = "tls"
host = "example.com"
min_days = 14

[[check]]
name = "Mail DNS"
type = "dnscheck"
domain = "example.com"
min_score = 60

[[check]]
name = "System clock"
type = "ntp"                 # server defaults to pool.ntp.org
max_offset = 500

[[check]]
name = "New IP propagated"
type = "propagation"
name_to_query = "example.com"
record = "A"
expect = ["93.184.216.34"]
"""


def _family(entry: dict) -> int | None:
    import socket

    value = str(entry.get("family", "")).lower()
    return {
        "4": socket.AF_INET,
        "ipv4": socket.AF_INET,
        "6": socket.AF_INET6,
        "ipv6": socket.AF_INET6,
    }.get(value)


def _host(entry: dict, key: str = "host") -> str:
    return profile_diag.resolve_target(str(entry[key]))


def _run_ping(e: dict):
    from xping.diagnostics.ping import ping

    return ping(
        host=_host(e),
        count=int(e.get("count", 4)),
        timeout=float(e.get("timeout", 2.0)),
        interval=float(e.get("interval", 0.2)),
        quiet=True,
        family=_family(e),
    )


def _run_tcp(e: dict):
    from xping.diagnostics.tcp import tcp

    return tcp(
        host=_host(e),
        port=int(e["port"]),
        count=int(e.get("count", 1)),
        timeout=float(e.get("timeout", 2.0)),
        interval=float(e.get("interval", 0.2)),
        quiet=True,
        family=_family(e),
    )


def _run_http(e: dict):
    from xping.diagnostics.http import http_diagnose

    return http_diagnose(
        url=str(e["url"]), timeout=float(e.get("timeout", 8.0)), quiet=True, family=_family(e)
    )


def _run_tls(e: dict):
    from xping.diagnostics.tls import tls

    return tls(
        host=_host(e),
        port=int(e.get("port", 443)),
        timeout=float(e.get("timeout", 5.0)),
        quiet=True,
        family=_family(e),
    )


def _run_lookup(e: dict):
    from xping.diagnostics.lookup import lookup

    return lookup(
        host=str(e["host"]), full=bool(e.get("full", False)), quiet=True, server=e.get("server")
    )


def _run_dnscheck(e: dict):
    from xping.diagnostics.dnscheck import dnscheck

    return dnscheck(domain=str(e["domain"]), quiet=True)


def _run_health(e: dict):
    from xping.diagnostics.health import health

    return health(
        host=_host(e),
        count=int(e.get("count", 8)),
        timeout=float(e.get("timeout", 2.0)),
        quiet=True,
        family=_family(e),
    )


def _run_propagation(e: dict):
    from xping.diagnostics.propagation import propagation

    expect = e.get("expect")
    if isinstance(expect, str):
        expect = [expect]
    return propagation(
        name=str(e["name_to_query"]),
        rtype=str(e.get("record", "A")),
        expected=expect,
        servers=e.get("servers"),
        quiet=True,
    )


def _run_udp(e: dict):
    from xping.diagnostics.udp import udp

    return udp(
        host=_host(e),
        port=int(e["port"]),
        count=int(e.get("count", 1)),
        timeout=float(e.get("timeout", 2.0)),
        interval=float(e.get("interval", 0.2)),
        probe=str(e.get("probe", "auto")),
        hex_payload=e.get("payload"),
        quiet=True,
        family=_family(e),
    )


def _run_ntp(e: dict):
    from xping.diagnostics.ntp import ntp

    return ntp(
        server=_host(e, "server"),
        count=int(e.get("count", 2)),
        timeout=float(e.get("timeout", 2.0)),
        quiet=True,
        family=_family(e),
    )


def _run_blocklist(e: dict):
    from xping.diagnostics.blocklist import blocklist

    return blocklist(
        target=_host(e, "target"),
        extra_zones=e.get("zones"),
        timeout=float(e.get("timeout", 5.0)),
        quiet=True,
    )


# type -> (runner, required keys, target key)
CHECK_TYPES: dict[str, tuple[Callable[[dict], Any], tuple[str, ...], str]] = {
    "ping": (_run_ping, ("host",), "host"),
    "tcp": (_run_tcp, ("host", "port"), "host"),
    "udp": (_run_udp, ("host", "port"), "host"),
    "ntp": (_run_ntp, (), "server"),
    "http": (_run_http, ("url",), "url"),
    "tls": (_run_tls, ("host",), "host"),
    "lookup": (_run_lookup, ("host",), "host"),
    "dnscheck": (_run_dnscheck, ("domain",), "domain"),
    "blocklist": (_run_blocklist, ("target",), "target"),
    "health": (_run_health, ("host",), "host"),
    "propagation": (_run_propagation, ("name_to_query",), "name_to_query"),
}
THRESHOLD_KEYS = (
    "max_loss",
    "max_latency",
    "expect_status",
    "min_days",
    "min_score",
    "max_offset",
)


class ConfigError(ValueError):
    """The check file is missing, unreadable or invalid."""


def _decode(raw: bytes, path: str) -> str:
    """UTF-8 (with or without BOM) or BOM-marked UTF-16. The latter is what
    Windows PowerShell 5 writes for `xping check --example > checks.toml`."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path}: not UTF-8 or UTF-16 text ({exc.reason})") from exc


def load_config(path: str) -> list[dict]:
    """Parse *path* (TOML or JSON) into validated check entries (defaults applied)."""
    file = Path(path)
    try:
        text = _decode(file.read_bytes(), path)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from exc

    if file.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}: invalid JSON ({exc})") from exc
    else:
        try:
            import tomllib
        except ModuleNotFoundError as exc:  # Python 3.10
            raise ConfigError(
                "TOML check files need Python 3.11+; use a .json file instead"
            ) from exc
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: invalid TOML ({exc})") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a table/object")
    defaults = data.get("defaults", {})
    checks = data.get("check", data.get("checks"))
    if not isinstance(defaults, dict) or not isinstance(checks, list) or not checks:
        raise ConfigError(f'{path}: define at least one [[check]] (TOML) or "checks": [...] (JSON)')

    entries = []
    for index, raw in enumerate(checks, 1):
        if not isinstance(raw, dict):
            raise ConfigError(f"check #{index}: must be a table/object")
        entry = {**defaults, **raw}
        kind = str(entry.get("type", "")).lower()
        if kind not in CHECK_TYPES:
            valid = ", ".join(CHECK_TYPES)
            raise ConfigError(
                f"check #{index}: unknown type '{entry.get('type')}' (valid: {valid})"
            )
        missing = [k for k in CHECK_TYPES[kind][1] if k not in entry]
        if missing:
            raise ConfigError(f"check #{index} ({kind}): missing {', '.join(missing)}")
        entry["type"] = kind
        if kind == "ntp":
            entry.setdefault("server", "pool.ntp.org")
        entry.setdefault("name", f"{kind} {entry[CHECK_TYPES[kind][2]]}")
        entries.append(entry)
    return entries


def _run_one(entry: dict) -> CheckOutcome:
    runner, _required, target_key = CHECK_TYPES[entry["type"]]
    target = str(entry[target_key])
    if entry["type"] == "tcp":
        target = f"{target}:{entry['port']}"
    elif entry["type"] == "udp":
        target = f"{target}:{entry['port']}/udp"
    started = time.perf_counter()
    try:
        result = runner(entry)
        failures = evaluate(result, SimpleNamespace(**{k: entry.get(k) for k in THRESHOLD_KEYS}))
        ok = not failures
        detail = failures[0].message if failures else check_view.describe(result)
    except Exception as exc:  # one broken check must not abort the batch
        result, ok, detail = None, False, f"error: {exc}"
    elapsed = (time.perf_counter() - started) * 1000
    return CheckOutcome(entry["name"], entry["type"], target, ok, detail, round(elapsed, 1), result)


def run_checks(path: str, workers: int = 8, quiet: bool = False) -> CheckReport:
    entries = load_config(path)
    report = CheckReport(source=path)

    if not quiet:
        print(section_header(f"CHECKS  {Path(path).name}", "◆"))
        print(kv("Checks", str(len(entries))))
        print(kv("Parallel", str(min(workers, len(entries)))))
        print()

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c(f"Running {len(entries)} checks…", BRAND_TEAL))
        spinner.start()
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(entries)))) as pool:
            report.outcomes = list(pool.map(_run_one, entries))
    finally:
        if spinner:
            spinner.stop()

    if not quiet:
        check_view.print_report(report)
    return report
