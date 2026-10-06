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

from xping.diagnostics import profile as profile_diag
from xping.models.check import CheckOutcome, CheckReport
from xping.render import BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.views import check as check_view
from xping.verdict import evaluate

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


def _run_smtp(e: dict):
    from xping.diagnostics.smtp import smtp

    return smtp(
        host=_host(e),
        port=int(e.get("port", 25)),
        timeout=float(e.get("timeout", 10.0)),
        use_mx=not e.get("no_mx", False),
        quiet=True,
        family=_family(e),
    )


def _run_trace(e: dict):
    from xping.diagnostics.trace import trace

    port = e.get("port")
    return trace(
        host=_host(e),
        max_hops=int(e.get("max_hops", 30)),
        timeout=float(e.get("timeout", 2.0)),
        probes=int(e.get("probes", 1)),
        quiet=True,
        family=_family(e),
        tcp_port=int(port) if port else (443 if e.get("tcp") else None),
    )


def _run_mtr(e: dict):
    from xping.diagnostics.mtr import mtr

    port = e.get("port")
    return mtr(
        host=_host(e),
        max_hops=int(e.get("max_hops", 30)),
        cycles=int(e.get("cycles", 5)),
        timeout=float(e.get("timeout", 2.0)),
        quiet=True,
        family=_family(e),
        tcp_port=int(port) if port else (443 if e.get("tcp") else None),
    )


def _run_wifi(e: dict):
    from xping.diagnostics.wifi import wifi

    interface = e.get("interface")
    return wifi(interface=interface if interface != "default" else None, quiet=True)


def _run_doctor(e: dict):
    from xping.diagnostics.doctor import doctor

    target = e.get("target")
    return doctor(
        target=_host(e, "target") if target and target != "internet" else None,
        port=int(e.get("port", 443)),
        quiet=True,
    )


def _run_speedtest(e: dict):
    from xping.diagnostics.speedtest import speedtest

    return speedtest(
        connections=int(e.get("connections", 4)),
        duration=float(e.get("duration", 8.0)),
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
    "smtp": (_run_smtp, ("host",), "host"),
    "lookup": (_run_lookup, ("host",), "host"),
    "dnscheck": (_run_dnscheck, ("domain",), "domain"),
    "blocklist": (_run_blocklist, ("target",), "target"),
    "health": (_run_health, ("host",), "host"),
    "propagation": (_run_propagation, ("name_to_query",), "name_to_query"),
    "trace": (_run_trace, ("host",), "host"),
    "mtr": (_run_mtr, ("host",), "host"),
    "wifi": (_run_wifi, (), "interface"),
    "doctor": (_run_doctor, (), "target"),
    "speedtest": (_run_speedtest, (), "server"),
}
# Types that measure this machine's own link: run one at a time after the
# parallel batch, so they neither disturb nor get disturbed by other checks.
EXCLUSIVE_TYPES = ("speedtest",)
# Shown as the target when an entry does not name one
_DEFAULT_TARGETS = {
    "ntp": "pool.ntp.org",
    "wifi": "default",
    "doctor": "internet",
    "speedtest": "cloudflare",
}
THRESHOLD_KEYS = (
    "max_loss",
    "max_latency",
    "expect_status",
    "min_days",
    "min_score",
    "max_offset",
    "require_tls",
    "min_signal",
    "min_download",
    "min_upload",
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
    return normalize(checks, defaults)


def normalize(checks: list, defaults: dict | None = None) -> list[dict]:
    """Validate raw check tables and apply *defaults* (also used for checks
    built from command-line targets)."""
    defaults = defaults or {}
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
        target_key = CHECK_TYPES[kind][2]
        if kind in _DEFAULT_TARGETS and not entry.get(target_key):
            entry[target_key] = _DEFAULT_TARGETS[kind]
        entry.setdefault("name", f"{kind} {entry[target_key]}")
        entries.append(entry)
    return entries


def display_target(entry: dict) -> str:
    """What a check is aimed at, as shown in reports: host, host:port, URL…"""
    target = str(entry.get(CHECK_TYPES[entry["type"]][2], ""))
    if entry["type"] == "tcp":
        return f"{target}:{entry['port']}"
    if entry["type"] == "udp":
        return f"{target}:{entry['port']}/udp"
    return target


def _run_one(entry: dict) -> CheckOutcome:
    runner = CHECK_TYPES[entry["type"]][0]
    target = display_target(entry)
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


def run_entries(entries: list[dict], workers: int = 8) -> list[CheckOutcome]:
    """Run *entries* in parallel (exclusive types one at a time afterwards);
    outcomes come back in the same order."""
    parallel = [e for e in entries if e["type"] not in EXCLUSIVE_TYPES]
    outcomes: dict[int, CheckOutcome] = {}
    if parallel:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(parallel)))) as pool:
            for entry, outcome in zip(parallel, pool.map(_run_one, parallel), strict=True):
                outcomes[id(entry)] = outcome
    for entry in entries:
        if entry["type"] in EXCLUSIVE_TYPES:
            outcomes[id(entry)] = _run_one(entry)
    return [outcomes[id(e)] for e in entries]


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
        report.outcomes = run_entries(entries, workers)
    finally:
        if spinner:
            spinner.stop()

    if not quiet:
        check_view.print_report(report)
    return report


# ── the default check file, --init, and checks from command-line targets ──

DEFAULT_DIR = Path.home() / ".xping"


def default_file(base: Path | None = None) -> Path:
    """~/.xping/checks.toml, or checks.json when only that one exists."""
    root = base or DEFAULT_DIR
    toml, json_file = root / "checks.toml", root / "checks.json"
    return json_file if json_file.exists() and not toml.exists() else toml


class NoCheckFile(ConfigError):
    """No check file was given and there is none in the default place."""


def require_default(base: Path | None = None) -> Path:
    path = default_file(base)
    if not path.exists():
        raise NoCheckFile(
            f"no check file yet ({_tilde(path)})\n"
            "  create one:        xping check --init\n"
            "  or watch targets:  xping monitor 1.1.1.1 router.local db.internal:5432"
        )
    return path


def _tilde(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def entries_from_targets(targets: list[str]) -> list[dict]:
    """Quick checks without a file: a URL becomes an http check, host:port
    (or [IPv6]:port) a tcp check, anything else a ping."""
    import ipaddress

    raw: list[dict] = []
    for target in targets:
        if target.startswith(("http://", "https://")):
            raw.append({"type": "http", "url": target, "name": target})
            continue
        host, port = target, None
        if target.startswith("[") and "]:" in target:  # [2001:db8::1]:22
            host, _, port = target[1:].partition("]:")
        elif target.count(":") == 1:  # host:port (a bare IPv6 address has more colons)
            host, _, port = target.partition(":")
        if port is not None:
            if not port.isdigit() or not 0 < int(port) < 65536:
                raise ConfigError(f"'{target}': port must be 1-65535")
            raw.append({"type": "tcp", "host": host, "port": int(port), "name": target})
        else:
            try:
                ipaddress.ip_address(host.strip("[]"))
                host = host.strip("[]")
            except ValueError:
                pass
            raw.append({"type": "ping", "host": host, "name": target})
    return normalize(raw)


def _starter(gateway: str | None, as_json: bool) -> str:
    checks = []
    if gateway:
        checks.append(("Router", {"type": "ping", "host": gateway, "every": 10}))
    checks += [
        ("Internet (Cloudflare DNS)", {"type": "ping", "host": "1.1.1.1", "every": 10}),
        ("Internet (Google DNS)", {"type": "ping", "host": "8.8.8.8", "every": 10}),
        ("DNS resolution", {"type": "lookup", "host": "cloudflare.com", "every": 60}),
        ("HTTPS", {"type": "http", "url": "https://www.cloudflare.com", "every": 60}),
    ]
    if as_json:
        data = {
            "defaults": {"timeout": 3, "fail_after": 3},
            "checks": [{"name": name, **body} for name, body in checks],
        }
        return json.dumps(data, indent=2) + "\n"
    lines = [
        "# xping checks - used by `xping check` and `xping monitor` when no file is given.",
        "# Edit freely: add your own servers, ports, URLs and thresholds.",
        "# All check types and keys: `xping check --example`, or `man xping`.",
        "",
        "[defaults]",
        "timeout = 3",
        "fail_after = 3      # monitor: count as DOWN only after 3 failures in a row",
    ]
    for name, body in checks:
        lines += ["", "[[check]]", f'name = "{name}"']
        lines += [f"{k} = {json.dumps(v)}" for k, v in body.items()]
    lines += [
        "",
        "# [[check]]",
        '# name = "Database"',
        '# type = "tcp"',
        '# host = "db.example.com"',
        "# port = 5432",
        "# max_latency = 50",
        "",
    ]
    return "\n".join(lines)


def init_file(base: Path | None = None, gateway: str | None = None) -> tuple[Path, bool]:
    """Create the default check file; (path, created). An existing file is
    never overwritten."""
    existing = default_file(base)
    if existing.exists():
        return existing, False
    try:
        import tomllib  # noqa: F401  (TOML files need Python 3.11+)

        path, as_json = existing, False
    except ModuleNotFoundError:
        path, as_json = existing.with_suffix(".json"), True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_starter(gateway, as_json), encoding="utf-8")
    return path, True
