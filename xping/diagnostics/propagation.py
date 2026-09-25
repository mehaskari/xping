"""
xping.diagnostics.propagation — ask many public resolvers the same question.

After changing a DNS record, resolvers keep serving the old value until its
TTL expires. Querying the big public resolvers (plus your own) side by side
shows whether a change has propagated — and ``--expect`` turns it into a
pass/fail check for scripts.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from xping.diagnostics.lookup import normalize_record, query
from xping.models.propagation import PropagationResult, ResolverAnswer
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.views import propagation as propagation_view

PUBLIC_RESOLVERS: tuple[tuple[str, str], ...] = (
    ("Google", "8.8.8.8"),
    ("Cloudflare", "1.1.1.1"),
    ("Quad9", "9.9.9.9"),
    ("OpenDNS", "208.67.222.222"),
    ("AdGuard", "94.140.14.14"),
    ("Control D", "76.76.2.0"),
)
RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "NS", "TXT")


def _system_server() -> str | None:
    """First nameserver of the system resolver (for the raw-UDP path)."""
    from xping.diagnostics.net import _read_resolv

    servers = _read_resolv("/etc/resolv.conf")
    return servers[0] if servers else None


def _ask(label: str, server: str | None, name: str, rtype: str) -> ResolverAnswer:
    status, records, elapsed = query(name, rtype, server)
    if status == "ERROR" and server is None:
        # no dig: send the raw query to the configured system nameserver
        fallback = _system_server()
        if fallback:
            status, records, elapsed = query(name, rtype, fallback)
            server = fallback
    return ResolverAnswer(label, server, status, records, round(elapsed, 1))


def propagation(
    name: str,
    rtype: str = "A",
    expected: list[str] | None = None,
    servers: list[str] | None = None,
    include_system: bool = True,
    quiet: bool = False,
) -> PropagationResult:
    """Query *name* / *rtype* on every resolver and compare the answers."""
    name = name.strip().rstrip(".")
    rtype = rtype.upper()
    result = PropagationResult(
        name=name,
        rtype=rtype,
        expected=[normalize_record(rtype, e) for e in (expected or [])],
    )
    targets: list[tuple[str, str | None]] = list(PUBLIC_RESOLVERS)
    targets += [(f"Custom {s}", s) for s in servers or []]
    if include_system:
        targets.insert(0, ("System", None))

    if not quiet:
        print(section_header(f"DNS PROPAGATION  {name}  {rtype}", "◑"))
        print(kv("Query", c(f"{name} {rtype}", BRAND_TEAL, BOLD)))
        if result.expected:
            print(kv("Expect", ", ".join(result.expected)))
        print(kv("Resolvers", str(len(targets))))
        print()

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c(f"Asking {len(targets)} resolvers…", BRAND_TEAL))
        spinner.start()
    try:
        with ThreadPoolExecutor(max_workers=len(targets)) as pool:
            result.answers = list(pool.map(lambda t: _ask(t[0], t[1], name, rtype), targets))
    finally:
        if spinner:
            spinner.stop()

    if not quiet:
        propagation_view.print_result(result)
    return result
