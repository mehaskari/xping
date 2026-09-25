"""
xping.trace — Live animated traceroute.
Each hop is printed the moment its probe response arrives.
"""

import random
import select
import socket
import subprocess
import sys
import time

from xping.diagnostics import asn as asn_lookup
from xping.diagnostics import icmp
from xping.diagnostics.deps import is_available, require, warn_missing
from xping.diagnostics.platform_cmds import parse_trace_line, trace_command, trace_tool
from xping.diagnostics.resolve import is_ipv6, resolve
from xping.models.trace import Hop
from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.errors import resolve_error
from xping.render.views import trace as trace_view

ICMP_TIME_EXCEEDED = 11
ICMP_DEST_UNREACH = 3
ICMP_ECHO_REPLY_T = 0


def _reverse(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None


def _raw_trace_hop(
    dest_ip: str, ttl: int, port: int, timeout: float = 2.0, probes: int = 3
) -> Hop | None:
    """One TTL level, `probes` UDP packets. Returns None if no permission."""
    rtts, last_ip = [], None

    for _ in range(probes):
        try:
            recv_s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            recv_s.settimeout(timeout)
            send_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            send_s.setsockopt(socket.SOL_IP, socket.IP_TTL, ttl)
        except PermissionError:
            return None

        t0 = time.perf_counter()
        try:
            send_s.sendto(b"xping-probe", (dest_ip, port))
            if select.select([recv_s], [], [], timeout)[0]:
                data, (src_ip, _) = recv_s.recvfrom(512)
                elapsed = (time.perf_counter() - t0) * 1000
                ihl = (data[0] & 0x0F) * 4  # IPv4 header length; options make it > 20
                itype = data[ihl]
                if itype in (ICMP_TIME_EXCEEDED, ICMP_DEST_UNREACH, ICMP_ECHO_REPLY_T):
                    last_ip = src_ip
                    rtts.append(elapsed)
                else:
                    rtts.append(-1.0)
            else:
                rtts.append(-1.0)
        except Exception:
            rtts.append(-1.0)
        finally:
            send_s.close()
            recv_s.close()

    timed_out = all(r < 0 for r in rtts)
    hostname = _reverse(last_ip) if last_ip and not timed_out else None
    return Hop(ttl=ttl, host=hostname, ip=last_ip, rtts=rtts, timeout=timed_out)


def _subprocess_trace_live(
    host: str, max_hops: int, probes: int, on_hop, timeout: float = 2.0
) -> list[Hop]:
    """Run system traceroute/tracert and call on_hop(Hop) for each hop line."""
    if trace_tool() is None:
        return []

    cmd = trace_command(host, max_hops, probes, timeout)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
    except FileNotFoundError:
        return []

    hops: list[Hop] = []

    for line in proc.stdout:
        parsed = parse_trace_line(line.rstrip())
        if parsed is None:
            continue

        ttl, rtts, ip, hostname = parsed
        hop = Hop(
            ttl=ttl,
            host=hostname,
            ip=ip,
            rtts=rtts,
            timeout=not rtts or all(r < 0 for r in rtts),
        )
        hops.append(hop)
        on_hop(hop)

    proc.wait()
    return hops


def _icmp_trace_hop(dest_ip: str, ttl: int, timeout: float = 2.0, probes: int = 3) -> Hop | None:
    """One TTL level using hop-limited ICMP echoes — unprivileged on macOS
    and Linux ping sockets, IPv4 and IPv6. None if no ICMP socket opens."""
    rtts: list[float] = []
    last_ip = None
    base = random.randint(1, 0xFFFF - 1000)
    for i in range(probes):
        answer = icmp.probe(dest_ip, ttl, base + ttl * probes + i, timeout)
        if answer is None:
            return None
        responder, rtt = answer
        rtts.append(rtt)
        if responder:
            last_ip = responder
    timed_out = all(r < 0 for r in rtts)
    hostname = _reverse(last_ip) if last_ip and not timed_out else None
    return Hop(ttl=ttl, host=hostname, ip=last_ip, rtts=rtts, timeout=timed_out)


def _native_hop(dest_ip: str, ttl: int, timeout: float, probes: int) -> Hop | None:
    """Best native probe: unprivileged ICMP, then raw UDP (IPv4, root)."""
    hop = _icmp_trace_hop(dest_ip, ttl, timeout=timeout, probes=probes)
    if hop is None and not is_ipv6(dest_ip):
        hop = _raw_trace_hop(dest_ip, ttl, 33434 + ttl, timeout=timeout, probes=probes)
    return hop


def discover_path(
    dest_ip: str, max_hops: int = 30, timeout: float = 2.0, probes: int = 1
) -> list[tuple[int, str | None]] | None:
    """
    One-shot native path discovery for `mtr`: ttl -> hop IP (or None if
    that hop was silent). Returns None if no native socket is available,
    in which case the caller should fall back to `discover_path_subprocess`.
    """
    path: list[tuple[int, str | None]] = []
    for ttl in range(1, max_hops + 1):
        hop = _native_hop(dest_ip, ttl, timeout, probes)
        if hop is None:
            return None
        path.append((ttl, None if hop.timeout else hop.ip))
        if hop.ip == dest_ip and not hop.timeout:
            break
    return path


def discover_path_subprocess(
    host: str, max_hops: int = 30, probes: int = 1
) -> list[tuple[int, str | None]]:
    """System-traceroute fallback path discovery for `mtr`."""
    hops = _subprocess_trace_live(host, max_hops, probes, on_hop=lambda _h: None)
    return [(hop.ttl, None if hop.timeout else hop.ip) for hop in hops]


def trace(
    host: str,
    max_hops: int = 30,
    timeout: float = 2.0,
    probes: int = 3,
    quiet: bool = False,
    family: int | None = None,
    asn: bool = False,
) -> list[Hop]:

    try:
        dest_ip = resolve(host, family)
    except socket.gaierror:
        if not quiet:
            resolve_error(host)
        return []

    if not quiet:
        print(section_header(f"TRACEROUTE  {host}", "◎"))
        print(kv("Destination", c(host, BRAND_TEAL, BOLD)))
        print(kv("IP", c(dest_ip, BRAND_INDIGO)))
        print(kv("Max hops", str(max_hops)))
        print(kv("Probes/hop", str(probes)))
        print()
        trace_view.hop_header()

    hops: list[Hop] = []

    for ttl in range(1, max_hops + 1):
        spinner = None
        if not quiet and sys.stdout.isatty():
            spinner = Spinner(c(f"Probing hop {ttl}…", BRAND_TEAL))
            spinner.start()

        hop = _native_hop(dest_ip, ttl, timeout, probes)
        if spinner:
            spinner.stop()

        if hop is None:
            # No usable ICMP/raw socket: hand the whole trace to the system tool.
            if not is_available("traceroute"):
                require("traceroute", "traceroute")
                return []
            if not quiet:
                warn_missing("ICMP sockets", "using system traceroute")

            def on_hop(found: Hop) -> None:
                if asn:
                    asn_lookup.annotate(found)
                if not quiet:
                    trace_view.print_hop(found)

            hops = _subprocess_trace_live(dest_ip, max_hops, probes, on_hop=on_hop, timeout=timeout)
            break

        if asn:
            asn_lookup.annotate(hop)
        hops.append(hop)
        if not quiet:
            trace_view.print_hop(hop)

        if hop.ip == dest_ip and not hop.timeout:
            break

    if not quiet:
        trace_view.hop_separator()
        print()
        trace_view.print_summary(hops, host, dest_ip)
    return hops
