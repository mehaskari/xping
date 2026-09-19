"""CLI entry point."""

from __future__ import annotations

import os
import sys

from xping.cli.commands import (
    cmd_about,
    cmd_all,
    cmd_completion,
    cmd_deps,
    cmd_dnscheck,
    cmd_health,
    cmd_http,
    cmd_ipscan,
    cmd_listen,
    cmd_lookup,
    cmd_mtr,
    cmd_mtu,
    cmd_osdetect,
    cmd_ping,
    cmd_portscan,
    cmd_profile,
    cmd_rdns,
    cmd_speedtest,
    cmd_sweep,
    cmd_tcp,
    cmd_tls,
    cmd_trace,
    cmd_whois,
    print_version,
)
from xping.cli.parser import build_parser
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


def _is_bare_host(argv: list[str]) -> str | None:
    """Return the host if argv looks like `xping <host>` (no subcommand)."""
    known_commands = {
        "ping",
        "trace",
        "lookup",
        "tcp",
        "portscan",
        "sweep",
        "ipscan",
        "all",
        "rdns",
        "dnscheck",
        "tls",
        "http",
        "whois",
        "health",
        "mtr",
        "mtu",
        "profile",
        "speedtest",
        "completion",
        "listen",
        "osdetect",
        "deps",
        "about",
        "-h",
        "--help",
        "-V",
        "--version",
    }
    if len(argv) == 1:
        token = argv[0]
        if token not in known_commands and not token.startswith("-"):
            return token
    return None


def main() -> None:
    raw_argv = sys.argv[1:]

    # ── Bare host: xping 8.8.8.8  or  xping google.com ────────────────────
    bare = _is_bare_host(raw_argv)
    if bare is not None:
        is_tty = sys.stdout.isatty()
        if is_tty:
            print(banner())
        try:
            from xping.diagnostics import profile as profile_diag
            from xping.diagnostics.ping import ping

            resolved = profile_diag.resolve_target(bare)
            ping(host=resolved, count=5, quiet=False)
            if is_tty:
                _print_next_steps(bare)
        except KeyboardInterrupt:
            print(c("\n\n  Interrupted.", BRAND_AMBER))
        sys.exit(0)

    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print_version()
        sys.exit(0)

    if not args.command:
        print(banner())
        parser.print_help()
        sys.exit(0)

    if sys.stdout.isatty() and not (
        getattr(args, "json", False)
        or getattr(args, "csv", False)
        or getattr(args, "markdown", False)
    ):
        print(banner())

    dispatch = {
        "ping": cmd_ping,
        "trace": cmd_trace,
        "lookup": cmd_lookup,
        "tcp": cmd_tcp,
        "portscan": cmd_portscan,
        "sweep": cmd_sweep,
        "ipscan": cmd_ipscan,
        "all": cmd_all,
        "rdns": cmd_rdns,
        "dnscheck": cmd_dnscheck,
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
        "completion": cmd_completion,
        "deps": cmd_deps,
        "about": cmd_about,
    }

    try:
        dispatch[args.command](args)
    except KeyboardInterrupt:
        print(c("\n\n  Interrupted.", BRAND_AMBER))
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:
        error(str(exc))
        if os.environ.get("XPING_DEBUG"):
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()
