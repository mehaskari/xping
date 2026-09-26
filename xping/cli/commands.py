"""CLI command handlers."""

from __future__ import annotations

import argparse
import json

from xping import __author__, __copyright__, __email__, __license__, __url__, __version__
from xping.cli.errors import UsageError
from xping.cli.export import emit_export, export_requested, output_suppressed
from xping.cli.verdict import evaluate
from xping.diagnostics import profile as profile_diag
from xping.diagnostics.blocklist import blocklist
from xping.diagnostics.bundle import run_bundle
from xping.diagnostics.check import EXAMPLE, ConfigError, run_checks
from xping.diagnostics.deps import print_deps_status
from xping.diagnostics.diff import diff
from xping.diagnostics.dnscheck import dnscheck
from xping.diagnostics.doctor import doctor
from xping.diagnostics.health import health
from xping.diagnostics.http import http_diagnose
from xping.diagnostics.ipscan import ipscan
from xping.diagnostics.listen import listen
from xping.diagnostics.lookup import lookup
from xping.diagnostics.mtr import mtr
from xping.diagnostics.mtu import mtu
from xping.diagnostics.net import net
from xping.diagnostics.notify import Notifier
from xping.diagnostics.ntp import ntp
from xping.diagnostics.osdetect import osdetect
from xping.diagnostics.ping import ping
from xping.diagnostics.ping import watch as ping_watch
from xping.diagnostics.portscan import portscan
from xping.diagnostics.propagation import propagation
from xping.diagnostics.rdns import rdns
from xping.diagnostics.resolve import family_of
from xping.diagnostics.speedtest import speedtest
from xping.diagnostics.sweep import sweep
from xping.diagnostics.tcp import tcp
from xping.diagnostics.tls import tls
from xping.diagnostics.trace import trace
from xping.diagnostics.udp import udp
from xping.diagnostics.watch import watch
from xping.diagnostics.whois import whois
from xping.render import (
    BOLD,
    BRAND_AMBER,
    BRAND_SLATE,
    BRAND_TEAL,
    BWHITE,
    DIM,
    c,
)


def _resolve_host(value: str) -> str:
    """Transparently substitute a saved profile name for its stored target."""
    return profile_diag.resolve_target(value)


def _watch_requested(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "watch", False) or getattr(args, "until_up", False))


def _notifier(args: argparse.Namespace, target: str, check: str):
    """Notifier for --notify / --webhook, or None when neither was given."""
    desktop = getattr(args, "notify", False)
    webhook = getattr(args, "webhook", None)
    if not (desktop or webhook):
        return None
    return Notifier(target, check, desktop=desktop, webhook=webhook)


def _require_watch_for_notify(args: argparse.Namespace) -> None:
    if (getattr(args, "notify", False) or getattr(args, "webhook", None)) and not (
        _watch_requested(args)
    ):
        flag = "--notify" if getattr(args, "notify", False) else "--webhook"
        watch_flags = "--watch" if args.command == "ping" else "--watch or --until-up"
        raise UsageError(f"{flag} only works in watch mode ({watch_flags})")


def _run_watch(args: argparse.Namespace, target: str, check: str, run_once, describe) -> object:
    """Shared --watch / --until-up driver: judge every run with the same
    verdict (and thresholds) as the exit code, and hand it to watch()."""
    if export_requested(args):
        raise UsageError("--watch/--until-up cannot be combined with --json/--csv/--markdown")
    if getattr(args, "quiet", False) and not getattr(args, "until_up", False):
        raise UsageError("--watch runs until Ctrl-C and cannot be combined with --quiet")

    def probe():
        result = run_once()
        failures = evaluate(result, args)
        latency, detail = describe(result)
        return (not failures, latency, failures[0].message if failures else detail)

    return watch(
        target,
        check,
        probe,
        every=args.every,
        until_up=getattr(args, "until_up", False),
        quiet=getattr(args, "quiet", False),
        notifier=_notifier(args, target, check),
    )


def cmd_ping(args: argparse.Namespace) -> object:
    _require_watch_for_notify(args)
    if getattr(args, "watch", False):
        if output_suppressed(args):
            raise UsageError(
                "--watch runs until Ctrl-C and cannot be combined with "
                "--json/--csv/--markdown/--quiet"
            )
        ping_watch(
            host=_resolve_host(args.host),
            timeout=args.timeout,
            interval=args.interval,
            family=family_of(args),
            notifier=_notifier(args, args.host, "ping"),
        )
        return None
    quiet = output_suppressed(args)
    result = ping(
        host=_resolve_host(args.host),
        count=args.count,
        timeout=args.timeout,
        interval=args.interval,
        quiet=quiet,
        family=family_of(args),
    )
    emit_export(result, args)
    return result


def cmd_trace(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = trace(
        host=_resolve_host(args.host),
        max_hops=args.max_hops,
        timeout=args.timeout,
        probes=args.probes,
        quiet=quiet,
        family=family_of(args),
        asn=args.asn,
        tcp_port=(args.port or 443) if (args.tcp or args.port) else None,
    )
    emit_export(result, args)
    return result


def cmd_lookup(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = lookup(
        host=_resolve_host(args.host),
        full=args.full,
        server=getattr(args, "server", None),
        doh=getattr(args, "doh", None),
        quiet=quiet,
    )
    emit_export(result, args)
    return result


def cmd_tcp(args: argparse.Namespace) -> object:
    _require_watch_for_notify(args)
    if _watch_requested(args):
        host = _resolve_host(args.host)
        return _run_watch(
            args,
            f"{args.host}:{args.port}",
            "tcp",
            lambda: tcp(
                host=host,
                port=args.port,
                count=1,
                timeout=args.timeout,
                quiet=True,
                family=family_of(args),
            ),
            lambda r: (r.avg_connect_ms, "connected"),
        )
    quiet = output_suppressed(args)
    result = tcp(
        host=_resolve_host(args.host),
        port=args.port,
        count=args.count,
        timeout=args.timeout,
        interval=args.interval,
        quiet=quiet,
        family=family_of(args),
    )
    emit_export(result, args)
    return result


def cmd_udp(args: argparse.Namespace) -> object:
    _require_watch_for_notify(args)
    host = _resolve_host(args.host)
    options = dict(
        host=host,
        port=args.port,
        timeout=args.timeout,
        probe=args.probe,
        hex_payload=args.payload,
        family=family_of(args),
    )
    if _watch_requested(args):
        return _run_watch(
            args,
            f"{args.host}:{args.port}/udp",
            "udp",
            lambda: udp(count=1, quiet=True, **options),
            lambda r: (r.avg_rtt_ms, r.attempts[0].detail if r.attempts else r.error or ""),
        )
    result = udp(count=args.count, interval=args.interval, quiet=output_suppressed(args), **options)
    emit_export(result, args)
    return result


def cmd_ntp(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = ntp(
        server=_resolve_host(args.server),
        count=args.count,
        timeout=args.timeout,
        quiet=quiet,
        family=family_of(args),
    )
    emit_export(result, args)
    return result


def cmd_portscan(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = portscan(
        host=_resolve_host(args.host),
        ports=args.ports,
        timeout=args.timeout,
        workers=args.workers,
        grab_banners=getattr(args, "banners", False),
        quiet=quiet,
        family=family_of(args),
    )
    emit_export(result, args)
    return result


def cmd_sweep(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = sweep(
        target=args.target,
        ports=args.ports,
        timeout=args.timeout,
        workers=args.workers,
        limit=args.limit,
        quiet=quiet,
    )
    emit_export(result, args)
    return result


def cmd_ipscan(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = ipscan(
        target=args.target,
        timeout=args.timeout,
        workers=args.workers,
        limit=args.limit,
        quiet=quiet,
    )
    emit_export(result, args)
    return result


def cmd_all(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = run_bundle(_resolve_host(args.host), quiet=quiet, family=family_of(args))
    emit_export(result, args)
    return result


def cmd_check(args: argparse.Namespace) -> object:
    if args.example:
        print(EXAMPLE, end="")
        return True
    if not args.file:
        raise UsageError("a check file is required (see: xping check --example)")
    quiet = output_suppressed(args)
    try:
        result = run_checks(args.file, workers=args.workers, quiet=quiet)
    except ConfigError as exc:
        raise UsageError(str(exc)) from exc
    emit_export(result, args)
    return result


def cmd_diff(args: argparse.Namespace) -> object:
    try:
        result = diff(
            args.before,
            args.after,
            max_regression=args.max_regression,
            quiet=output_suppressed(args),
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    emit_export(result, args)
    return result


def cmd_rdns(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = rdns(ip=args.ip, quiet=quiet)
    emit_export(result, args)
    return result


def cmd_blocklist(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = blocklist(
        target=_resolve_host(args.target),
        extra_zones=args.zone,
        timeout=args.timeout,
        quiet=quiet,
        show_all=args.all,
    )
    emit_export(result, args)
    return result


def cmd_propagation(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = propagation(
        name=args.name,
        rtype=args.rtype,
        expected=args.expect,
        servers=args.server,
        include_system=not args.no_system,
        quiet=quiet,
    )
    emit_export(result, args)
    return result


def cmd_tls(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = tls(
        host=_resolve_host(args.host),
        port=args.port,
        timeout=args.timeout,
        quiet=quiet,
        family=family_of(args),
    )
    emit_export(result, args)
    return result


def cmd_http(args: argparse.Namespace) -> object:
    _require_watch_for_notify(args)
    if _watch_requested(args):
        return _run_watch(
            args,
            args.url,
            "http",
            lambda: http_diagnose(
                url=args.url, timeout=args.timeout, quiet=True, family=family_of(args)
            ),
            lambda r: (r.total_ms, f"HTTP {r.status_code} {r.reason or ''}".strip()),
        )
    quiet = output_suppressed(args)
    result = http_diagnose(url=args.url, timeout=args.timeout, quiet=quiet, family=family_of(args))
    emit_export(result, args)
    return result


def cmd_whois(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = whois(domain=args.domain, quiet=quiet)
    emit_export(result, args)
    return result


def cmd_dnscheck(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = dnscheck(domain=_resolve_host(args.domain), quiet=quiet)
    emit_export(result, args)
    return result


def cmd_health(args: argparse.Namespace) -> object:
    _require_watch_for_notify(args)
    if _watch_requested(args):
        host = _resolve_host(args.host)
        return _run_watch(
            args,
            args.host,
            "health",
            lambda: health(
                host=host,
                count=args.count,
                timeout=args.timeout,
                quiet=True,
                family=family_of(args),
            ),
            lambda r: (r.ping.avg_rtt if r.ping else None, f"score {r.score} ({r.grade})"),
        )
    quiet = output_suppressed(args)
    result = health(
        host=_resolve_host(args.host),
        count=args.count,
        timeout=args.timeout,
        quiet=quiet,
        family=family_of(args),
    )
    emit_export(result, args)
    return result


def cmd_mtr(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = mtr(
        host=_resolve_host(args.host),
        max_hops=args.max_hops,
        cycles=args.cycles,
        timeout=args.timeout,
        interval=args.interval,
        quiet=quiet,
        family=family_of(args),
        asn=args.asn,
    )
    emit_export(result, args)
    return result


def cmd_mtu(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = mtu(
        host=_resolve_host(args.host),
        max_mtu=args.max_mtu,
        timeout=args.timeout,
        quiet=quiet,
        family=family_of(args),
    )
    emit_export(result, args)
    return result


def cmd_profile(args: argparse.Namespace) -> object:
    """Returns False when the requested profile operation failed (exit code 1)."""
    action = getattr(args, "profile_action", None)
    if action == "add":
        return profile_diag.add(args.name, args.target, port=args.port, note=args.note) is not None
    if action in ("remove", "rm"):
        return profile_diag.remove(args.name)
    if action == "show":
        return profile_diag.show(args.name) is not None
    if getattr(args, "names", False):
        for entry in profile_diag.list_profiles(quiet=True).profiles:
            print(entry.name)
        return True
    profile_diag.list_profiles()
    return True


def cmd_speedtest(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = speedtest(connections=args.connections, duration=args.duration, quiet=quiet)
    emit_export(result, args)
    return result


def cmd_completion(args: argparse.Namespace) -> object:
    from xping.cli import completion

    if args.install or args.uninstall:
        shell = args.shell or completion.detect_shell()
        if shell is None:
            raise UsageError("cannot detect your shell from $SHELL — name it: bash, zsh or fish")
        if args.install:
            actions = completion.install(shell)
            for action in actions:
                print(c("  ✔ ", BRAND_TEAL) + action)
            print()
            print(c(f"  {shell} completion installed. Open a new terminal, or run:", BWHITE))
            if shell == "fish":
                print(c("    (fish picks it up automatically)", DIM))
            else:
                home = completion.Path.home()
                rc = completion._tilde(completion._rc_file(shell, home), home)
                print(c(f"    source {rc}", BRAND_TEAL))
            print(c("  Re-run after upgrading xping to pick up new commands and flags.", DIM))
        else:
            actions = completion.uninstall(shell)
            for action in actions or ["nothing to remove"]:
                print(c("  ✔ ", BRAND_TEAL) + action)
        return True
    if not args.shell:
        raise UsageError("name a shell (bash, zsh, fish) or use --install")
    print(completion.generate(args.shell), end="")
    return True


def cmd_config(args: argparse.Namespace) -> object:
    from xping.cli import config as user_config
    from xping.render import print_table

    if args.example:
        print(user_config.EXAMPLE, end="")
        return True
    from xping.cli.parser import build_parser

    try:
        config = user_config.load()
        user_config.apply(build_parser(), config)  # validate every entry
    except user_config.ConfigError as exc:
        print()
        print(c(f"  ✘ {exc}", BRAND_AMBER, BOLD))
        print(c("  Fix the file, or run with XPING_CONFIG=none to ignore it.", DIM))
        print()
        return False
    path = user_config.config_path()
    print()
    if config.disabled:
        print(c("  Config disabled (XPING_CONFIG=none) — built-in defaults are used.", BWHITE))
    elif not config.loaded:
        print(c(f"  No config file at {path}", BWHITE))
        print(c("  Create one with:", DIM))
        print(c(f"    xping config --example > {path}", BRAND_TEAL))
    else:
        print(c("  Config file  ", BRAND_SLATE) + c(str(config.path), BRAND_TEAL, BOLD))
        rows = [
            [c(f"[{section}]", BRAND_AMBER), key.replace("_", "-"), json.dumps(value)]
            for section, values in config.sections.items()
            for key, value in values.items()
        ]
        print()
        if rows:
            print_table(["Section", "Option", "Value"], rows)
        else:
            print(c("  (empty)", DIM))
        print()
        print(c("  Options given on the command line always win.", DIM))
    print()
    return True


def cmd_listen(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = listen(proto_filter=getattr(args, "proto", None), quiet=quiet)
    emit_export(result, args)
    return result


def cmd_osdetect(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = osdetect(host=_resolve_host(args.host), quiet=quiet, family=family_of(args))
    emit_export(result, args)
    return result


def cmd_net(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = net(public=not args.no_public, quiet=quiet, show_all=args.all)
    emit_export(result, args)
    return result


def cmd_doctor(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    target = _resolve_host(args.host) if args.host else None
    result = doctor(target=target, port=args.port, quiet=quiet)
    emit_export(result, args)
    return result


def cmd_deps(_args: argparse.Namespace) -> None:
    print_deps_status()


def cmd_about(_args: argparse.Namespace) -> None:
    lines = [
        "",
        c("  xping", BRAND_TEAL, BOLD) + c(f"  v{__version__}", DIM),
        c("  Beautiful CLI network diagnostics", BWHITE),
        "",
        c("  Author   ", BRAND_SLATE)
        + c(f"{__author__}", BWHITE, BOLD)
        + c(f"  <{__email__}>", DIM),
        c("  License  ", BRAND_SLATE) + c(__license__, BWHITE),
        c("  Source   ", BRAND_SLATE) + c(__url__, BRAND_TEAL),
        c("  " + __copyright__, DIM),
        "",
        c("  Attribution notice:", BRAND_AMBER, BOLD),
        c("  Any fork, derivative work, or redistribution of this software", DIM),
        c("  must visibly credit: " + __author__ + " <" + __email__ + ">", DIM),
        "",
    ]
    for line in lines:
        print(line)


def print_version() -> None:
    print(c(f"xping {__version__}", BRAND_TEAL, BOLD) + c(f"  by {__author__}", BRAND_SLATE))
