"""CLI command handlers."""

from __future__ import annotations

import argparse

from xping import __author__, __copyright__, __email__, __license__, __url__, __version__
from xping.cli.errors import UsageError
from xping.cli.export import emit_export, output_suppressed
from xping.diagnostics import profile as profile_diag
from xping.diagnostics.bundle import run_bundle
from xping.diagnostics.deps import print_deps_status
from xping.diagnostics.dnscheck import dnscheck
from xping.diagnostics.health import health
from xping.diagnostics.http import http_diagnose
from xping.diagnostics.ipscan import ipscan
from xping.diagnostics.listen import listen
from xping.diagnostics.lookup import lookup
from xping.diagnostics.mtr import mtr
from xping.diagnostics.mtu import mtu
from xping.diagnostics.osdetect import osdetect
from xping.diagnostics.ping import ping
from xping.diagnostics.ping import watch as ping_watch
from xping.diagnostics.portscan import portscan
from xping.diagnostics.rdns import rdns
from xping.diagnostics.speedtest import speedtest
from xping.diagnostics.sweep import sweep
from xping.diagnostics.tcp import tcp
from xping.diagnostics.tls import tls
from xping.diagnostics.trace import trace
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


def cmd_ping(args: argparse.Namespace) -> object:
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
        )
        return
    quiet = output_suppressed(args)
    result = ping(
        host=_resolve_host(args.host),
        count=args.count,
        timeout=args.timeout,
        interval=args.interval,
        quiet=quiet,
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
    )
    emit_export(result, args)
    return result


def cmd_lookup(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = lookup(
        host=_resolve_host(args.host),
        full=args.full,
        server=getattr(args, "server", None),
        quiet=quiet,
    )
    emit_export(result, args)
    return result


def cmd_tcp(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = tcp(
        host=_resolve_host(args.host),
        port=args.port,
        count=args.count,
        timeout=args.timeout,
        interval=args.interval,
        quiet=quiet,
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
    result = run_bundle(_resolve_host(args.host), quiet=quiet)
    emit_export(result, args)
    return result


def cmd_rdns(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = rdns(ip=args.ip, quiet=quiet)
    emit_export(result, args)
    return result


def cmd_tls(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = tls(host=_resolve_host(args.host), port=args.port, timeout=args.timeout, quiet=quiet)
    emit_export(result, args)
    return result


def cmd_http(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = http_diagnose(url=args.url, timeout=args.timeout, quiet=quiet)
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
    quiet = output_suppressed(args)
    result = health(
        host=_resolve_host(args.host), count=args.count, timeout=args.timeout, quiet=quiet
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
    )
    emit_export(result, args)
    return result


def cmd_mtu(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = mtu(
        host=_resolve_host(args.host), max_mtu=args.max_mtu, timeout=args.timeout, quiet=quiet
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
    profile_diag.list_profiles()
    return True


def cmd_speedtest(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = speedtest(quiet=quiet)
    emit_export(result, args)
    return result


def cmd_completion(args: argparse.Namespace) -> object:
    from xping.cli.completion import generate

    try:
        print(generate(args.shell))
    except ValueError as exc:
        from xping.render.errors import error

        error(str(exc))
        return False
    return True


def cmd_listen(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = listen(proto_filter=getattr(args, "proto", None), quiet=quiet)
    emit_export(result, args)
    return result


def cmd_osdetect(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = osdetect(host=_resolve_host(args.host), quiet=quiet)
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
