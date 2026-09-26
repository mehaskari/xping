"""CLI entry point."""

from __future__ import annotations

import os
import sys

from xping.cli import config as user_config
from xping.cli.commands import (
    cmd_about,
    cmd_all,
    cmd_blocklist,
    cmd_check,
    cmd_completion,
    cmd_config,
    cmd_deps,
    cmd_dnscheck,
    cmd_doctor,
    cmd_health,
    cmd_http,
    cmd_ipscan,
    cmd_listen,
    cmd_lookup,
    cmd_mtr,
    cmd_mtu,
    cmd_net,
    cmd_ntp,
    cmd_osdetect,
    cmd_ping,
    cmd_portscan,
    cmd_profile,
    cmd_propagation,
    cmd_rdns,
    cmd_speedtest,
    cmd_sweep,
    cmd_tcp,
    cmd_tls,
    cmd_trace,
    cmd_udp,
    cmd_whois,
    cmd_wifi,
    print_version,
)
from xping.cli.errors import UsageError
from xping.cli.parser import build_parser
from xping.cli.verdict import evaluate
from xping.render import BOLD, BRAND_AMBER, BRAND_SLATE, BRAND_TEAL, DIM, banner, c, error

_NEXT_STEPS = [
    ("trace", "hop-by-hop path"),
    ("health", "health score"),
    ("mtr", "live per-hop ping"),
    ("lookup", "DNS records"),
    ("tls", "TLS certificate"),
    ("http", "HTTP diagnostics"),
    ("portscan", "port scan"),
    ("whois", "WHOIS info"),
    ("dnscheck", "DNS health check"),
    ("osdetect", "OS fingerprint"),
    ("speedtest", "speed test"),
]


def _print_next_steps(host: str) -> None:
    """Print a hint about other commands the user can run for this host."""
    print()
    print(c("  ── What else can you do with this host? ", BRAND_SLATE, BOLD) + c("─" * 26, DIM))
    print()
    for cmd, desc in _NEXT_STEPS:
        if cmd in ("speedtest",):
            cmd_str = c(f"xping {cmd}", BRAND_TEAL)
        else:
            cmd_str = c(f"xping {cmd} {host}", BRAND_TEAL)
        print(f"  {cmd_str}  {c(desc, DIM)}")
    print()


_DISPATCH = {
    "ping": cmd_ping,
    "trace": cmd_trace,
    "lookup": cmd_lookup,
    "tcp": cmd_tcp,
    "udp": cmd_udp,
    "ntp": cmd_ntp,
    "portscan": cmd_portscan,
    "sweep": cmd_sweep,
    "ipscan": cmd_ipscan,
    "all": cmd_all,
    "check": cmd_check,
    "rdns": cmd_rdns,
    "dnscheck": cmd_dnscheck,
    "blocklist": cmd_blocklist,
    "propagation": cmd_propagation,
    "tls": cmd_tls,
    "http": cmd_http,
    "whois": cmd_whois,
    "health": cmd_health,
    "mtr": cmd_mtr,
    "mtu": cmd_mtu,
    "profile": cmd_profile,
    "speedtest": cmd_speedtest,
    "listen": cmd_listen,
    "osdetect": cmd_osdetect,
    "net": cmd_net,
    "wifi": cmd_wifi,
    "doctor": cmd_doctor,
    "completion": cmd_completion,
    "config": cmd_config,
    "deps": cmd_deps,
    "about": cmd_about,
}


_WORKS_WITHOUT_CONFIG = {"config", "completion", "about", "deps", "-h", "--help", "-V", "--version"}


def _is_bare_host(argv: list[str]) -> str | None:
    """Return the host if argv looks like `xping <host>` (no subcommand)."""
    if len(argv) == 1:
        token = argv[0]
        if token not in _DISPATCH and not token.startswith("-"):
            return token
    return None


def main() -> None:
    raw_argv = sys.argv[1:]

    parser = build_parser()
    try:
        user_config.apply(parser, user_config.load())
    except user_config.ConfigError as exc:
        # `xping config` and help must still work — they are how you fix it
        if not raw_argv or raw_argv[0] not in _WORKS_WITHOUT_CONFIG:
            parser.exit(2, f"xping: config error: {exc}\n  (check it with: xping config)\n")
        parser = build_parser()

    # ── Bare host: xping 8.8.8.8  or  xping google.com ────────────────────
    bare = _is_bare_host(raw_argv)
    if bare is not None:
        is_tty = sys.stdout.isatty()
        try:
            from xping.diagnostics import profile as profile_diag
            from xping.diagnostics.ping import ping
            from xping.diagnostics.resolve import family_of

            opts = parser.parse_args(["ping", bare])  # [ping] config applies here too
            resolved = profile_diag.resolve_target(bare)
            result = ping(
                host=resolved,
                count=opts.count,
                timeout=opts.timeout,
                interval=opts.interval,
                quiet=False,
                family=family_of(opts),
            )
            if is_tty:
                _print_next_steps(bare)
        except KeyboardInterrupt:
            print(c("\n\n  Interrupted.", BRAND_AMBER))
            sys.exit(130)
        sys.exit(1 if evaluate(result) else 0)

    args = parser.parse_args()
    user_config.resolve_conflicts(build_parser(), args, raw_argv)

    if args.version:
        print_version()
        sys.exit(0)

    if not args.command:
        print(banner())
        parser.print_help()
        sys.exit(0)

    try:
        result = _DISPATCH[args.command](args)
    except KeyboardInterrupt:
        print(c("\n\n  Interrupted.", BRAND_AMBER))
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)
    except UsageError as exc:
        parser.exit(2, f"xping {args.command}: error: {exc}\n")
    except Exception as exc:
        error(str(exc))
        if os.environ.get("XPING_DEBUG"):
            raise
        sys.exit(1)

    sys.exit(_exit_code(result, args))


def _exit_code(result, args) -> int:
    """0 when the check passed, 1 when it failed. Threshold violations are
    explained on stderr (other failures were already shown by the view)."""
    failures = evaluate(result, args)
    if not failures:
        return 0
    if not getattr(args, "quiet", False):
        for failure in failures:
            if failure.threshold:
                error(failure.message)
    return 1


if __name__ == "__main__":
    main()
