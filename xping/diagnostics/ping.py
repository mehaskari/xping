"""
xping.ping — Live animated ICMP ping.
Each reply is printed the moment it arrives — no buffering.
"""

import os
import socket
import struct
import time
import select
import subprocess
import sys

from xping.diagnostics.deps import warn_missing, require, is_available
from xping.diagnostics.platform_cmds import ping_command, parse_ping_rtt
from xping.models.ping import PingResult
from xping.render import (
    c, section_header, kv,
    BRAND_TEAL, BRAND_INDIGO, BOLD,
)
from xping.render.animations import Spinner
from xping.render.errors import error, resolve_error
from xping.render.views import ping as ping_view

ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY   = 0


def _checksum(data: bytes) -> int:
    s, n = 0, len(data) % 2
    for i in range(0, len(data) - n, 2):
        s += data[i] + (data[i + 1] << 8)
    if n:
        s += data[-1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def _build_packet(seq: int, pid: int) -> bytes:
    header  = struct.pack("bbHHh", ICMP_ECHO_REQUEST, 0, 0, pid, seq)
    payload = b"xping___" * 4
    chk     = _checksum(header + payload)
    return struct.pack("bbHHh", ICMP_ECHO_REQUEST, 0, chk, pid, seq) + payload


def _icmp_ping(host: str, seq: int, timeout: float = 2.0) -> float | None:
    """One ICMP echo. Returns RTT ms, -1.0 on timeout, None on no permission."""
    pid = os.getpid() & 0xFFFF
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    except PermissionError:
        return None

    sock.settimeout(timeout)
    dest   = socket.gethostbyname(host)
    packet = _build_packet(seq, pid)
    sent   = time.perf_counter()
    try:
        sock.sendto(packet, (dest, 1))
        while True:
            if not select.select([sock], [], [], timeout)[0]:
                return -1.0
            raw, _ = sock.recvfrom(1024)
            recv_t = time.perf_counter()
            ip_len = (raw[0] & 0x0F) * 4
            icmp   = raw[ip_len:]
            itype, _, _, rid, rseq = struct.unpack("bbHHh", icmp[:8])
            if itype == ICMP_ECHO_REPLY and rid == pid and rseq == seq:
                return (recv_t - sent) * 1000
    except Exception:  # noqa: BLE001
        return -1.0
    finally:
        sock.close()


def _subprocess_ping_one(host: str, timeout: float) -> float:
    """System ping, one packet. Returns RTT ms or -1."""
    try:
        proc = subprocess.run(
            ping_command(host, timeout),
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return parse_ping_rtt(output)
    except Exception:  # noqa: BLE001
        return -1.0


def ping_once(host_ip: str, seq: int, timeout: float = 2.0) -> float | None:
    """Public single-probe wrapper (used by `mtr`). Returns RTT ms, -1.0 on
    timeout, or None if raw sockets are unavailable."""
    return _icmp_ping(host_ip, seq, timeout)


def ping_once_subprocess(host_ip: str, timeout: float = 2.0) -> float:
    """Public single-probe wrapper around the system `ping` fallback."""
    return _subprocess_ping_one(host_ip, timeout)


def ping(host: str, count: int = 5, timeout: float = 2.0,
         interval: float = 0.5, quiet: bool = False) -> PingResult:

    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror:
        if not quiet:
            resolve_error(host)
        return PingResult(host=host, ip="?", count=count, resolved=False)

    if not quiet:
        print(section_header(f"PING  {host}", "◉"))
        print(kv("Target",   c(host, BRAND_TEAL, BOLD)))
        print(kv("IP",       c(ip, BRAND_INDIGO)))
        print(kv("Packets",  str(count)))
        print(kv("Interval", f"{interval}s"))
        print(kv("Timeout",  f"{timeout}s / packet"))
        print()

    rtts: list[float] = []
    use_subprocess    = False

    try:
        for seq in range(1, count + 1):
            spinner = None
            if not quiet and sys.stdout.isatty():
                spinner_label = c(f"Waiting for reply #{seq}", BRAND_TEAL)
                spinner = Spinner(spinner_label)
                spinner.start()

            t0 = time.perf_counter()

            if use_subprocess:
                rtt = _subprocess_ping_one(host, timeout)
            else:
                rtt = _icmp_ping(host, seq, timeout)
                if rtt is None:
                    use_subprocess = True
                    if not is_available("ping"):
                        if spinner:
                            spinner.stop()
                        require("ping", "ICMP ping fallback")
                        return PingResult(host=host, ip=ip, count=count)
                    if not quiet:
                        if spinner:
                            spinner.stop()
                        warn_missing("raw sockets",
                                     "using system ping (run as root for native mode)")
                        spinner = None
                    rtt = _subprocess_ping_one(host, timeout)

            elapsed = time.perf_counter() - t0

            if spinner:
                spinner.stop()

            rtts.append(rtt)
            if not quiet:
                ping_view.print_line(seq, ip, rtt, count)

            if seq < count:
                remaining = interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)

    except KeyboardInterrupt:
        if spinner:
            spinner.stop()
        print()

    result = PingResult(host=host, ip=ip, count=count, rtts=rtts)
    if not quiet:
        ping_view.print_summary(result)
    return result


def watch(host: str, timeout: float = 2.0, interval: float = 1.0) -> None:
    """Continuous live ping with in-place sparkline (Ctrl-C to stop)."""
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror:
        from xping.render.errors import resolve_error
        resolve_error(host)
        return

    from xping.render import section_header, kv, BRAND_TEAL, BRAND_INDIGO, BOLD, c

    print(section_header(f"PING WATCH  {host}", "◉"))
    print(kv("Target", c(host, BRAND_TEAL, BOLD)))
    print(kv("IP", c(ip, BRAND_INDIGO)))
    print(kv("Interval", f"{interval}s"))
    print(kv("Stop", "Ctrl-C"))
    print()

    rtts: list[float] = []
    use_subprocess = False
    printed_rows = 0

    try:
        seq = 0
        while True:
            seq += 1
            t0 = time.perf_counter()

            if use_subprocess:
                rtt = _subprocess_ping_one(host, timeout)
            else:
                rtt = _icmp_ping(host, seq, timeout)
                if rtt is None:
                    use_subprocess = True
                    rtt = _subprocess_ping_one(host, timeout)

            elapsed = time.perf_counter() - t0
            rtts.append(rtt)
            printed_rows = ping_view.redraw_watch(rtts, printed_rows)

            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print()
        result = PingResult(host=host, ip=ip, count=len(rtts), rtts=rtts)
        ping_view.print_summary(result)
