"""
xping.diagnostics.mtr — Combined live traceroute + ping ("My Traceroute").
Discovers the path to a host, then continuously pings every hop for
several cycles, reporting per-hop loss%, latency, and jitter — updated
live, like the classic `mtr` tool.
"""

import socket
import time

from xping.diagnostics.deps import is_available, require, warn_missing
from xping.diagnostics.ping import ping_once, ping_once_subprocess
from xping.diagnostics.trace import discover_path, discover_path_subprocess
from xping.models.mtr import MtrHop, MtrResult
from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header
from xping.render.errors import resolve_error
from xping.render.views import mtr as mtr_view


def _reverse(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None


def mtr(
    host: str,
    max_hops: int = 30,
    cycles: int = 10,
    timeout: float = 2.0,
    interval: float = 0.3,
    quiet: bool = False,
) -> MtrResult:
    """Run a combined traceroute + ping report for *host*."""
    try:
        dest_ip = socket.gethostbyname(host)
    except socket.gaierror:
        if not quiet:
            resolve_error(host)
        return MtrResult(host=host, error=f"Cannot resolve '{host}'")

    result = MtrResult(host=host, dest_ip=dest_ip)

    if not quiet:
        print(section_header(f"MTR  {host}", "◈"))
        print(kv("Destination", c(host, BRAND_TEAL, BOLD)))
        print(kv("IP", c(dest_ip, BRAND_INDIGO)))
        print(kv("Cycles", str(cycles)))
        print()

    path = discover_path(dest_ip, max_hops=max_hops, timeout=timeout)
    use_subprocess_ping = False

    if path is None:
        if not is_available("traceroute"):
            if not quiet:
                require("traceroute", "MTR path discovery")
            result.error = "No raw-socket permission and no system traceroute available"
            return result
        if not quiet:
            warn_missing(
                "raw sockets", "using system traceroute/ping (run as root for native mode)"
            )
        path = discover_path_subprocess(host, max_hops=max_hops)
        use_subprocess_ping = True

    if not path:
        result.error = "Could not discover a path to the destination"
        return result

    hops = [MtrHop(ttl=ttl, ip=ip) for ttl, ip in path]
    for hop in hops:
        if hop.ip:
            hop.host = _reverse(hop.ip)
    result.hops = hops

    printed_rows = 0
    for cycle in range(1, cycles + 1):
        for hop in hops:
            if not hop.ip:
                hop.rtts.append(-1.0)
                continue
            if use_subprocess_ping:
                rtt = ping_once_subprocess(hop.ip, timeout)
            else:
                rtt = ping_once(hop.ip, cycle, timeout)
                if rtt is None:
                    use_subprocess_ping = True
                    rtt = ping_once_subprocess(hop.ip, timeout)
            hop.rtts.append(rtt)

        result.cycles = cycle
        if not quiet:
            printed_rows = mtr_view.redraw(hops, cycle, cycles, printed_rows)
        if cycle < cycles:
            time.sleep(interval)

    if not quiet:
        mtr_view.print_final(hops)
    return result
