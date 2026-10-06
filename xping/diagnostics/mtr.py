"""
xping.diagnostics.mtr — Combined live traceroute + ping ("My Traceroute").
Discovers the path to a host, then continuously pings every hop for
several cycles, reporting per-hop loss%, latency, and jitter — updated
live, like the classic `mtr` tool.
"""

import socket
import time

from xping.diagnostics import asn as asn_lookup
from xping.diagnostics import tcptrace
from xping.diagnostics.deps import is_available, require, warn_missing
from xping.diagnostics.ping import ping_once, ping_once_subprocess
from xping.diagnostics.resolve import resolve
from xping.diagnostics.trace import discover_path, discover_path_subprocess
from xping.models.mtr import MtrHop, MtrResult
from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header
from xping.render.errors import error, resolve_error
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
    family: int | None = None,
    asn: bool = False,
    tcp_port: int | None = None,
) -> MtrResult:
    """Run a combined traceroute + ping report for *host*. With *tcp_port*
    every probe is a TCP SYN to that port (like ``trace --tcp``), which gets
    through firewalls that drop ICMP."""
    try:
        dest_ip = resolve(host, family)
    except socket.gaierror:
        if not quiet:
            resolve_error(host)
        return MtrResult(host=host, error=f"Cannot resolve '{host}'")

    result = MtrResult(host=host, dest_ip=dest_ip, tcp_port=tcp_port)

    tracer = None
    if tcp_port is not None:
        if not tcptrace.supported():
            result.error = "TCP mtr needs Linux or macOS"
            if not quiet:
                error(result.error, hint="Use the default ICMP mtr on this system.")
            return result
        try:
            tracer = tcptrace.TcpTracer(dest_ip, tcp_port)
        except OSError as exc:
            result.error = f"TCP mtr unavailable: {exc}"
            if not quiet:
                error(result.error)
            return result

    if not quiet:
        print(section_header(f"MTR  {host}", "◈"))
        print(kv("Destination", c(host, BRAND_TEAL, BOLD)))
        print(kv("IP", c(dest_ip, BRAND_INDIGO)))
        if tcp_port is not None:
            print(kv("Method", f"TCP SYN to port {tcp_port}"))
        print(kv("Cycles", str(cycles)))
        print()

    if tracer is not None:
        with tracer:
            return _run(result, tracer, max_hops, cycles, timeout, interval, quiet, asn)

    path = discover_path(dest_ip, max_hops=max_hops, timeout=timeout)
    use_subprocess_ping = False

    if path is None:
        if not is_available("traceroute"):
            if not quiet:
                require("traceroute", "MTR path discovery")
            result.error = "No raw-socket permission and no system traceroute available"
            return result
        if not quiet:
            warn_missing("ICMP sockets", "using system traceroute/ping")
        path = discover_path_subprocess(dest_ip, max_hops=max_hops)
        use_subprocess_ping = True

    if not path:
        result.error = "Could not discover a path to the destination"
        return result

    hops = [MtrHop(ttl=ttl, ip=ip) for ttl, ip in path]
    for hop in hops:
        if hop.ip:
            hop.host = _reverse(hop.ip)
    if asn:
        asn_lookup.annotate_all(hops)
    result.hops = hops

    printed_rows = 0
    for cycle in range(1, cycles + 1):
        for hop in hops:
            if not hop.ip:
                hop.rtts.append(-1.0)
                continue
            rtt: float | None
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


def _run(result, tracer, max_hops, cycles, timeout, interval, quiet, asn) -> MtrResult:
    """TCP mode: discover the path and probe every hop with TCP SYNs whose
    TTL expires at that hop (the destination answers the connect itself)."""
    path: list[tuple[int, str | None]] = []
    for ttl in range(1, max_hops + 1):
        responder, _rtt = tracer.probe(ttl, timeout)
        path.append((ttl, responder))
        if responder == result.dest_ip:
            break
    if not any(ip for _ttl, ip in path):
        result.error = "Could not discover a path to the destination"
        return result

    hops = [MtrHop(ttl=ttl, ip=ip) for ttl, ip in path]
    for hop in hops:
        if hop.ip:
            hop.host = _reverse(hop.ip)
    if asn:
        asn_lookup.annotate_all(hops)
    result.hops = hops

    printed_rows = 0
    for cycle in range(1, cycles + 1):
        for hop in hops:
            if not hop.ip:
                hop.rtts.append(-1.0)
                continue
            responder, rtt = tracer.probe(hop.ttl, timeout)
            hop.rtts.append(rtt if responder else -1.0)
        result.cycles = cycle
        if not quiet:
            printed_rows = mtr_view.redraw(hops, cycle, cycles, printed_rows)
        if cycle < cycles:
            time.sleep(interval)

    if not quiet:
        mtr_view.print_final(hops)
    return result
