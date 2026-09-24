"""
xping.diagnostics.osdetect — OS fingerprinting from TTL and TCP window.
Reads the TTL from a ping response to guess the OS family.
No raw sockets required — uses the system ping output.
"""

import re
import socket
import subprocess

from xping.diagnostics.platform_cmds import ping_command
from xping.models.osdetect import OsDetectResult
from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header
from xping.render.errors import resolve_error

# TTL heuristics: OS sets initial TTL; each hop decrements by 1.
# We check the received TTL and map to the nearest common initial TTL.
_TTL_SIGNATURES: list[tuple[range, str, str]] = [
    (range(241, 256), "Linux / Android", "initial TTL 255"),
    (range(113, 129), "Windows", "initial TTL 128"),
    (range(57, 65), "Linux", "initial TTL 64"),
    (range(248, 256), "Cisco IOS", "initial TTL 255"),
    (range(252, 256), "Solaris / AIX", "initial TTL 255"),
]

_TTL_RE = re.compile(r"ttl[=\s]+(\d+)", re.IGNORECASE)
_WIN_TTL_RE = re.compile(r"TTL=(\d+)", re.IGNORECASE)


def _extract_ttl(output: str) -> int | None:
    for pat in (_TTL_RE, _WIN_TTL_RE):
        m = pat.search(output)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def _guess_os(ttl: int) -> tuple[str, str]:
    """Map received TTL to (os_guess, reasoning)."""
    # Find the closest initial TTL that is >= the received TTL
    for init in (255, 128, 64, 32):
        if ttl <= init:
            closest = init
    mapping = {
        255: (
            "Linux / Unix / Network device",
            "initial TTL 255 — Linux kernel, Cisco IOS, Solaris",
        ),
        128: ("Windows", "initial TTL 128 — Windows family"),
        64: ("Linux / macOS / FreeBSD", "initial TTL 64  — Linux, macOS, FreeBSD"),
        32: ("Windows 95/NT (legacy)", "initial TTL 32  — old Windows"),
    }
    return mapping.get(closest, ("Unknown", f"TTL {ttl} — no match"))


def osdetect(host: str, quiet: bool = False) -> OsDetectResult:
    """Guess target OS from ping TTL."""
    result = OsDetectResult(host=host)

    try:
        ip = socket.gethostbyname(host)
        result.ip = ip
    except socket.gaierror:
        if not quiet:
            resolve_error(host)
        result.error = f"Cannot resolve '{host}'"
        return result

    if not quiet:
        print(section_header(f"OS FINGERPRINT  {host}", "◎"))
        print(kv("Target", c(host, BRAND_TEAL, BOLD)))
        print(kv("IP", c(ip, BRAND_INDIGO)))
        print(kv("Method", "TTL analysis (1 ICMP echo probe)"))
        print()

    cmd = ping_command(host, timeout=3.0)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        ttl = _extract_ttl(output)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        ttl = None

    if ttl is None:
        result.error = "No ICMP reply — host may be unreachable or ICMP is blocked"
        if not quiet:
            from xping.render.errors import error

            error(result.error)
        return result

    result.ttl = ttl
    os_guess, reasoning = _guess_os(ttl)
    result.os_guess = os_guess
    result.reasoning = reasoning

    if not quiet:
        from xping.render import BRAND_MINT, BWHITE, DIM
        from xping.render.tables import print_table

        rows = [
            ["Received TTL", c(str(ttl), BWHITE, BOLD)],
            ["OS guess", c(os_guess, BRAND_MINT, BOLD)],
            ["Reasoning", c(reasoning, DIM)],
        ]
        print_table(["Field", "Value"], rows)
        print()
        print(
            c(
                "  ⚠  TTL-based detection is a heuristic — VPNs and proxies "
                "can change the observed TTL.",
                DIM,
            )
        )
        print()
    return result
