"""
xping.diagnostics.mtu — Path MTU discovery.
Binary-searches for the largest ICMP payload that reaches the destination
without fragmentation, using the system ping's "don't fragment" flag —
the same technique behind the classic Path MTU Discovery workflow.

Raw sockets aren't used here on purpose: setting the DF bit and reading
back ICMP "fragmentation needed" errors portably across Linux, macOS, and
Windows is exactly what the platform's own `ping` already does, and the
existing platform_cmds fallback machinery handles the differences.
"""

import socket
import subprocess
import sys

from xping.diagnostics.deps import is_available, require
from xping.diagnostics.platform_cmds import mtu_probe_command, mtu_probe_succeeded
from xping.models.mtu import ICMP_OVERHEAD_BYTES, MtuResult
from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.errors import error, resolve_error
from xping.render.views import mtu as mtu_view

MIN_PAYLOAD = 68 - ICMP_OVERHEAD_BYTES
DEFAULT_MAX_MTU = 1500


def _probe(target: str, payload_size: int, timeout: float) -> bool:
    try:
        proc = subprocess.run(
            mtu_probe_command(target, payload_size, timeout),
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return mtu_probe_succeeded(output)
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def mtu(
    host: str, max_mtu: int = DEFAULT_MAX_MTU, timeout: float = 2.0, quiet: bool = False
) -> MtuResult:
    """Binary-search the path MTU to *host*."""
    result = MtuResult(host=host)

    try:
        ip = socket.gethostbyname(host)
        result.ip = ip
    except socket.gaierror:
        if not quiet:
            resolve_error(host)
        result.error = f"Cannot resolve '{host}'"
        return result

    if not quiet:
        print(section_header(f"PATH MTU DISCOVERY  {host}", "◖"))
        print(kv("Target", c(host, BRAND_TEAL, BOLD)))
        print(kv("IP", c(ip, BRAND_INDIGO)))
        print(kv("Search ceiling", f"{max_mtu} bytes"))
        print()

    if not is_available("ping"):
        if not quiet:
            require("ping", "Path MTU discovery")
        result.error = "system 'ping' is required for MTU discovery"
        return result

    lo = MIN_PAYLOAD
    hi = max_mtu - ICMP_OVERHEAD_BYTES
    if hi <= lo:
        result.error = "max-mtu is too small to probe"
        if not quiet:
            error(result.error)
        return result

    # Sanity probe at the smallest size: if even that gets no reply the
    # host is probably unreachable rather than MTU-limited.
    if not _probe(host, lo, timeout):
        result.error = f"No reply even at a {lo}-byte payload — host may be unreachable"
        if not quiet:
            error(result.error)
        return result

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Binary-searching path MTU…", BRAND_TEAL))
        spinner.start()

    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        ok = _probe(host, mid, timeout)
        result.probes.append({"size": mid, "ok": ok})
        if not quiet and not spinner:
            mtu_view.print_probe(mid, ok)
        if ok:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    if spinner:
        spinner.stop()

    result.path_mtu = best + ICMP_OVERHEAD_BYTES

    if not quiet:
        mtu_view.print_summary(result)
    return result
