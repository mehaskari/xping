"""CLI command handlers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xping import __author__, __copyright__, __email__, __license__, __url__, __version__
from xping.cli.errors import UsageError
from xping.cli.export import emit_export, export_requested, output_suppressed
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
from xping.diagnostics.ping import DOWN_AFTER_LOSSES, ping
from xping.diagnostics.ping import watch as ping_watch
from xping.diagnostics.portscan import portscan
from xping.diagnostics.propagation import propagation
from xping.diagnostics.rdns import rdns
from xping.diagnostics.resolve import family_of
from xping.diagnostics.smtp import smtp
from xping.diagnostics.speedtest import speedtest
from xping.diagnostics.sweep import sweep
from xping.diagnostics.tcp import tcp
from xping.diagnostics.tls import tls
from xping.diagnostics.trace import trace
from xping.diagnostics.udp import udp
from xping.diagnostics.watch import watch
from xping.diagnostics.whois import whois
from xping.diagnostics.wifi import wifi
from xping.render import (
    BOLD,
    BRAND_AMBER,
    BRAND_SLATE,
    BRAND_TEAL,
    BWHITE,
    DIM,
    c,
)
from xping.verdict import evaluate


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
        raise UsageError(f"{flag} only works in watch mode (--watch or --until-up)")


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
        fail_after=getattr(args, "fail_after", None) or 1,
        recover_after=getattr(args, "recover_after", 1),
    )


def cmd_ping(args: argparse.Namespace) -> object:
    _require_watch_for_notify(args)
    if getattr(args, "until_up", False):
        host = _resolve_host(args.host)
        return _run_watch(
            args,
            args.host,
            "ping",
            lambda: ping(
                host=host, count=1, timeout=args.timeout, quiet=True, family=family_of(args)
            ),
            lambda r: (r.avg_rtt, "reply"),
        )
    if getattr(args, "watch", False):
        if output_suppressed(args):
            raise UsageError(
                "--watch runs until Ctrl-C and cannot be combined with "
                "--json/--csv/--markdown/--quiet"
            )
        return ping_watch(
            host=_resolve_host(args.host),
            timeout=args.timeout,
            interval=args.interval,
            family=family_of(args),
            notifier=_notifier(args, args.host, "ping"),
            fail_after=args.fail_after or DOWN_AFTER_LOSSES,
            recover_after=args.recover_after,
        )
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
    from xping.diagnostics import check as check_diag

    if args.example:
        print(EXAMPLE, end="")
        return True
    if args.init:
        from xping.diagnostics.net import net

        try:
            gateway = net(public=False, quiet=True).gateway_ipv4
        except Exception:  # no gateway is fine: the file just has no router check
            gateway = None
        path, created = check_diag.init_file(gateway=gateway)
        shown = check_diag._tilde(path)
        if created:
            print(c(f"  ✔ created {shown}", BRAND_TEAL))
            print(c("    edit it, then: xping check  ·  xping monitor", DIM))
        else:
            print(c(f"  {shown} already exists — left unchanged", DIM))
        print()
        return True
    quiet = output_suppressed(args)
    try:
        file = args.file or str(check_diag.require_default())
        result = run_checks(file, workers=args.workers, quiet=quiet)
    except ConfigError as exc:
        raise UsageError(str(exc)) from exc
    emit_export(result, args)
    return result


def cmd_monitor(args: argparse.Namespace) -> object:
    from xping.diagnostics import check as check_diag
    from xping.diagnostics.monitor import monitor

    targets = args.targets
    path, entries = None, None
    try:
        if not targets:
            path = str(check_diag.require_default())
        elif len(targets) == 1 and (
            targets[0].lower().endswith((".toml", ".json")) or Path(targets[0]).is_file()
        ):
            path = targets[0]
        else:
            entries = check_diag.entries_from_targets(targets)
        result = monitor(
            path,
            entries=entries,
            every=args.every,
            workers=args.workers,
            rounds=args.rounds,
            save=args.save,
            notify=args.notify,
            webhook=args.webhook,
            fail_after=args.fail_after,
            recover_after=args.recover_after,
            quiet=output_suppressed(args),
        )
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


def cmd_smtp(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = smtp(
        host=_resolve_host(args.host),
        port=args.port,
        timeout=args.timeout,
        use_mx=not args.no_mx,
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
        tcp_port=(args.port or 443) if (args.tcp or args.port) else None,
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
        # Only names `profile add` would accept: shell completion feeds these
        # to bash's `compgen -W`, which expands $(...) in its word list, so a
        # hand-edited profiles.json must not be able to inject commands.
        for entry in profile_diag.list_profiles(quiet=True).profiles:
            if profile_diag.valid_name(entry.name):
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
                rc_file = completion._rc_file(shell, home)
                rc = completion._tilde(rc_file, home) if rc_file else "your shell rc file"
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


def cmd_wifi(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    result = wifi(interface=args.interface, quiet=quiet, show_nearby=args.nearby)
    emit_export(result, args)
    return result


def cmd_doctor(args: argparse.Namespace) -> object:
    quiet = output_suppressed(args)
    target = _resolve_host(args.host) if args.host else None
    result = doctor(target=target, port=args.port, quiet=quiet)
    emit_export(result, args)
    return result


def cmd_report(args: argparse.Namespace) -> object:
    import sys
    from pathlib import Path

    from xping.diagnostics import history
    from xping.diagnostics.report import build
    from xping.exporters.html_report import to_html
    from xping.render import error

    command, target = args.report_command, args.report_target
    if target and not command:
        raise UsageError("name the command first, e.g. xping report ping example.net")
    try:
        since = history.parse_since(args.since) if args.since else None
    except ValueError as exc:
        raise UsageError(f"--since: {exc}") from exc
    try:
        result = build(command, target, since=since, last=args.last, compare=args.compare)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    if result.error:
        if not output_suppressed(args):
            if result.error == "nothing saved yet":
                hint = (
                    "xping report shows results kept with --save, e.g.\n"
                    "      xping monitor --save        (every check, all day)\n"
                    "      xping ping 1.1.1.1 --save   (one run)"
                )
            else:
                hint = "See what is saved with: xping history"
            error(result.error, hint=hint)
        emit_export(result, args)
        return result
    page = to_html(result, title=args.title)
    if args.output == "-":
        if export_requested(args):
            raise UsageError("-o - writes the page to stdout; it cannot be combined with an export")
        sys.stdout.write(page)
        return result
    path = Path(args.output).expanduser()
    try:
        path.write_text(page, encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"cannot write {path}: {exc.strerror or exc}") from exc
    result.path = str(path.resolve())
    if not output_suppressed(args):
        targets = len(result.series)
        print(
            c(f"  ✔ wrote {path}", BRAND_TEAL)
            + c(f"  ·  {targets} target{'s' if targets != 1 else ''}, {result.runs} runs", DIM)
        )
        print()
    emit_export(result, args)
    return result


def cmd_history(args: argparse.Namespace) -> object:
    from xping.diagnostics import history
    from xping.models.history import HistoryResult
    from xping.render.views import history as history_view

    command, target = args.history_command, args.history_target
    if target and not command:
        raise UsageError("name the command first, e.g. xping history ping example.net")
    if command and command not in history.TARGETS:
        raise UsageError(f"'{command}' results are not saved; one of: {', '.join(history.TARGETS)}")
    if args.clear:
        removed = history.clear(command, target)
        print(c(f"  ✔ removed {removed} saved history file(s)", BRAND_TEAL))
        return HistoryResult(command=command, target=target, cleared=removed)
    if not target:
        result = HistoryResult(entries=history.entries())
        if command:
            result.entries = [e for e in result.entries if e.command == command]
        if not output_suppressed(args):
            history_view.print_list(result)
        emit_export(result, args)
        return result
    try:
        since = history.parse_since(args.since) if args.since else None
    except ValueError as exc:
        raise UsageError(f"--since: {exc}") from exc
    result = history.show(command, target, last=args.last, since=since)
    if not output_suppressed(args):
        history_view.print_result(result)
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
