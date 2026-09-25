"""Native ICMP / ICMPv6 echo — works without root where the OS allows it.

Socket preference:

1. ``SOCK_DGRAM`` ("ping sockets"): unprivileged on macOS, and on Linux
   whenever the user's group is inside ``net.ipv4.ping_group_range`` (the
   default on most current distributions).
2. ``SOCK_RAW``: needs root or ``cap_net_raw``.

If neither can be opened the caller falls back to the system ``ping``.

Platform quirks handled here: macOS returns the IPv4 header on DGRAM
sockets while Linux strips it; Linux rewrites the echo identifier on DGRAM
sockets; and an ICMPv6 socket can see its own echo request on loopback.
Replies are therefore matched on type + sequence + a random payload token
rather than on the identifier.
"""

from __future__ import annotations

import os
import select
import socket
import struct
import sys
import time

ECHO_REQUEST_V4, ECHO_REPLY_V4 = 8, 0
ECHO_REQUEST_V6, ECHO_REPLY_V6 = 128, 129

_PROTO = {socket.AF_INET: socket.IPPROTO_ICMP, socket.AF_INET6: socket.IPPROTO_ICMPV6}


def checksum(data: bytes) -> int:
    """RFC 1071 Internet checksum."""
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def build_echo(family: int, ident: int, seq: int, payload: bytes) -> bytes:
    """Build an echo request. ICMPv6 checksums are filled in by the kernel."""
    icmp_type = ECHO_REQUEST_V6 if family == socket.AF_INET6 else ECHO_REQUEST_V4
    header = struct.pack("!BBHHH", icmp_type, 0, 0, ident & 0xFFFF, seq & 0xFFFF)
    if family == socket.AF_INET6:
        return header + payload
    csum = checksum(header + payload)
    return struct.pack("!BBHHH", icmp_type, 0, csum, ident & 0xFFFF, seq & 0xFFFF) + payload


def strip_ip_header(data: bytes, family: int) -> bytes:
    """Return the ICMP message, dropping an IPv4 header when one is present."""
    if family == socket.AF_INET and len(data) >= 20 and data[0] >> 4 == 4:
        return data[(data[0] & 0x0F) * 4 :]
    return data


def is_reply(icmp: bytes, family: int, seq: int, token: bytes) -> bool:
    if len(icmp) < 8 + len(token):
        return False
    reply_type = ECHO_REPLY_V6 if family == socket.AF_INET6 else ECHO_REPLY_V4
    icmp_type, _code, _csum, _ident, rseq = struct.unpack("!BBHHH", icmp[:8])
    return icmp_type == reply_type and rseq == seq & 0xFFFF and icmp[8 : 8 + len(token)] == token


def open_socket(family: int) -> tuple[socket.socket, str] | None:
    """Open the best available ICMP socket: (socket, "dgram"|"raw") or None."""
    for kind, sock_type in (("dgram", socket.SOCK_DGRAM), ("raw", socket.SOCK_RAW)):
        try:
            return socket.socket(family, sock_type, _PROTO[family]), kind
        except (PermissionError, OSError):
            continue
    return None


def socket_mode(family: int = socket.AF_INET) -> str | None:
    """Which native mode is usable right now ("dgram", "raw", or None)."""
    opened = open_socket(family)
    if opened is None:
        return None
    opened[0].close()
    return opened[1]


def echo(ip: str, seq: int, timeout: float = 2.0) -> float | None:
    """Send one echo to *ip*. Returns RTT in ms, -1.0 on timeout/error, or
    None when no native ICMP socket can be opened (use the system ping)."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    opened = open_socket(family)
    if opened is None:
        return None
    sock, _kind = opened
    token = os.urandom(8)
    packet = build_echo(family, os.getpid(), seq, token + b"xping___" * 3)
    address = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
    try:
        sock.settimeout(timeout)
        sent = time.perf_counter()
        sock.sendto(packet, address)
        deadline = sent + timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0 or not select.select([sock], [], [], remaining)[0]:
                return -1.0
            data, _ = sock.recvfrom(2048)
            received = time.perf_counter()
            if is_reply(strip_ip_header(data, family), family, seq, token):
                return (received - sent) * 1000
    except OSError:
        return -1.0
    finally:
        sock.close()


# ── TTL-limited probes (traceroute / mtr path discovery) ─────────────────────

# ICMP "time exceeded" / "destination unreachable" types per family
_ERRORS = {socket.AF_INET: (11, 3), socket.AF_INET6: (3, 1)}
_RECVERR = {  # Linux: ICMP errors for ping sockets arrive on the error queue
    socket.AF_INET: (getattr(socket, "SOL_IP", 0), getattr(socket, "IP_RECVERR", 11)),
    socket.AF_INET6: (getattr(socket, "SOL_IPV6", 41), getattr(socket, "IPV6_RECVERR", 25)),
}
_MSG_ERRQUEUE = getattr(socket, "MSG_ERRQUEUE", 0x2000)
# Windows has no MSG_DONTWAIT; there recv only runs after select() reported
# the socket readable, so a plain blocking recv is equivalent.
_MSG_DONTWAIT = getattr(socket, "MSG_DONTWAIT", 0)


def _set_hop_limit(sock: socket.socket, family: int, ttl: int) -> None:
    if family == socket.AF_INET6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_UNICAST_HOPS, ttl)
    else:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)


def _quoted_seq(icmp_msg: bytes, family: int) -> int | None:
    """Sequence number of our echo request quoted inside an ICMP error."""
    inner = icmp_msg[8:]
    if family == socket.AF_INET:
        if len(inner) < 20 or inner[0] >> 4 != 4:
            return None
        inner = inner[(inner[0] & 0x0F) * 4 :]
        request = ECHO_REQUEST_V4
    else:
        inner = inner[40:]  # fixed IPv6 header
        request = ECHO_REQUEST_V6
    if len(inner) < 8 or inner[0] != request:
        return None
    return struct.unpack("!H", inner[6:8])[0]


def _read_error_queue(sock: socket.socket, family: int, seq: int) -> str | None:
    """Linux ping sockets: return the router that reported an ICMP error for
    our probe *seq*, from the socket error queue (``IP_RECVERR``)."""
    try:
        data, ancdata, _flags, _addr = sock.recvmsg(2048, 512, _MSG_ERRQUEUE | _MSG_DONTWAIT)
    except (BlockingIOError, OSError):
        return None
    if len(data) < 8 or struct.unpack("!H", data[6:8])[0] != seq & 0xFFFF:
        return None
    level, opt = _RECVERR[family]
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if cmsg_level != level or cmsg_type != opt or len(cmsg_data) < 16:
            continue
        offender = cmsg_data[16:]  # struct sock_extended_err is 16 bytes
        try:
            if family == socket.AF_INET and len(offender) >= 8:
                return socket.inet_ntop(socket.AF_INET, offender[4:8])
            if family == socket.AF_INET6 and len(offender) >= 24:
                return socket.inet_ntop(socket.AF_INET6, offender[8:24])
        except (OSError, ValueError):
            return None
    return None


def probe(ip: str, ttl: int, seq: int, timeout: float = 2.0) -> tuple[str | None, float] | None:
    """Send one hop-limited echo toward *ip*.

    Returns ``(responder_ip, rtt_ms)`` — the router that said "time
    exceeded", or *ip* itself when the echo reached it — ``(None, -1.0)`` on
    timeout, or None when no ICMP socket is available at all.
    """
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    opened = open_socket(family)
    if opened is None:
        return None
    sock, kind = opened
    token = os.urandom(8)
    packet = build_echo(family, os.getpid(), seq, token + b"xping___" * 3)
    address = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
    use_errqueue = kind == "dgram" and sys.platform.startswith("linux")
    try:
        _set_hop_limit(sock, family, ttl)
        if use_errqueue:
            sock.setsockopt(*_RECVERR[family], 1)
        sent = time.perf_counter()
        sock.sendto(packet, address)
        deadline = sent + timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return None, -1.0
            if not select.select([sock], [], [], remaining)[0]:
                return None, -1.0
            if use_errqueue:
                router = _read_error_queue(sock, family, seq)
                if router:
                    return router, (time.perf_counter() - sent) * 1000
            try:
                data, addr = sock.recvfrom(2048, _MSG_DONTWAIT)
            except (BlockingIOError, InterruptedError):
                continue
            rtt = (time.perf_counter() - sent) * 1000
            msg = strip_ip_header(data, family)
            if is_reply(msg, family, seq, token):
                return addr[0], rtt
            if msg and msg[0] in _ERRORS[family] and _quoted_seq(msg, family) == seq & 0xFFFF:
                return addr[0], rtt
    except OSError:
        return None, -1.0
    finally:
        sock.close()
