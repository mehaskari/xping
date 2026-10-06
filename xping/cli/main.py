"""CLI entry point."""

from __future__ import annotations

import os
import sys

from xping.cli import commands, deprecated
from xping.cli import config as user_config
from xping.cli.commands import print_version
from xping.cli.errors import UsageError
from xping.cli.export import output_suppressed
from xping.cli.parser import build_parser
from xping.render import BOLD, BRAND_AMBER, BRAND_SLATE, BRAND_TEAL, DIM, banner, c, error, warn
from xping.verdict import evaluate

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


# Every subcommand NAME is handled by commands.cmd_NAME (a test checks that
# each parser subcommand has one), so a new command needs no entry here.
_DISPATCH = {
    name.removeprefix("cmd_"): handler
    for name, handler in vars(commands).items()
    if name.startswith("cmd_") and callable(handler)
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
    raw_argv = deprecated.rewrite(sys.argv[1:])

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

    args = parser.parse_args(raw_argv)
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

    code = _exit_code(result, args)
    if getattr(args, "save", False):
        _save(args, result, code == 0)
    sys.exit(code)


def _save(args, result, ok: bool) -> None:
    """Keep the result for `xping history` (--save). Watch runs and failed
    lookups without a result are skipped; a write error only warns."""
    from xping.diagnostics import history
    from xping.models.watch import WatchResult

    if result is None or isinstance(result, WatchResult | bool):
        return
    if args.command not in history.TARGETS:
        return  # e.g. monitor, which saves each of its checks itself
    if not (hasattr(result, "to_dict") or isinstance(result, list)):
        return
    try:
        target = history.TARGETS[args.command](args)
        path = history.record(args.command, target, result, ok)
    except (OSError, KeyError, AttributeError) as exc:
        warn(f"could not save to history: {exc}")
        return
    # confirm, unless the output must stay clean (-q, --json/--csv/--markdown)
    if not output_suppressed(args):
        runs = sum(1 for _ in path.open(encoding="utf-8"))
        print(
            c(f"  ✔ saved to history (run {runs})", BRAND_TEAL)
            + c(f"  ·  xping history {args.command} {target}", DIM)
        )
        print()


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
