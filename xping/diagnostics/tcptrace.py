"""
xping.diagnostics.tcptrace — TCP SYN traceroute without root.

Many firewalls drop ICMP echo and UDP probes, so a classic traceroute
stops somewhere in the middle. A TCP connection attempt to the port the
service really listens on (443, 22, …) is let through — and routers still
answer an expiring TTL with ICMP "time exceeded", quoting our TCP header.

Each probe is an ordinary non-blocking ``connect()`` with a small TTL:

* the connection succeeds or is refused  →  we reached the destination
  (a refusal still proves the host answered);
* a router answers "time exceeded"       →  that router is the hop.

Where the ICMP answer is read from, per platform — none needs root:

  Linux  the TCP socket's own error queue (``IP_RECVERR`` /
         ``IPV6_RECVERR``) names the router that sent the ICMP error.
  macOS  an unprivileged ICMP ("ping") socket also receives ICMP errors
         for other sockets; replies are matched on our quoted TCP ports.

Windows has neither, so ``probe`` returns None there.
"""

from __future__ import annotations

import errno
import select
import socket
import struct
import sys
import time

from xping.diagnostics import icmp

_REACHED = {0, errno.ECONNREFUSED, getattr(errno, "WSAECONNREFUSED", -1)}
_IN_PROGRESS = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 0}
# ICMP "time exceeded" / "destination unreachable" per family
_ICMP_ERRORS = {socket.AF_INET: (11, 3), socket.AF_INET6: (3, 1)}


def supported() -> bool:
    return sys.platform.startswith("linux") or sys.platform == "darwin"


def quoted_ports(message: bytes, family: int) -> tuple[int, int] | None:
    """(source port, destination port) of the TCP segment quoted inside an
    ICMP error message (outer IPv4 header already stripped)."""
    if len(message) < 8 or message[0] not in _ICMP_ERRORS[family]:
        return None
    inner = message[8:]
    if family == socket.AF_INET:
        if len(inner) < 20 or inner[0] >> 4 != 4 or inner[9] != socket.IPPROTO_TCP:
            return None
        inner = inner[(inner[0] & 0x0F) * 4 :]
    else:
        if len(inner) < 40 or inner[0] >> 4 != 6 or inner[6] != socket.IPPROTO_TCP:
            return None  # extension headers before TCP are not followed
        inner = inner[40:]
    if len(inner) < 4:
        return None
    return struct.unpack("!HH", inner[:4])


def _offender(ancdata, family: int) -> str | None:
    """Router address from a Linux ``sock_extended_err`` control message."""
    level = (
        getattr(socket, "SOL_IP", 0)
        if family == socket.AF_INET
        else getattr(socket, "SOL_IPV6", 41)
    )
    for cmsg_level, _cmsg_type, data in ancdata:
        if cmsg_level != level or len(data) < 16:
            continue
        offender = data[16:]
        try:
            if family == socket.AF_INET and len(offender) >= 8:
                return socket.inet_ntop(socket.AF_INET, offender[4:8])
            if family == socket.AF_INET6 and len(offender) >= 24:
                return socket.inet_ntop(socket.AF_INET6, offender[8:24])
        except (OSError, ValueError):
            return None
    return None


class TcpTracer:
    """Sends TCP SYN probes with a given TTL toward ``dest_ip:port``.

    Open once per trace (the macOS listener socket is shared by every
    probe) and close afterwards; usable as a context manager."""

    def __init__(self, dest_ip: str, port: int):
        self.dest_ip = dest_ip
        self.port = port
        self.family = socket.AF_INET6 if ":" in dest_ip else socket.AF_INET
        self.linux = sys.platform.startswith("linux")
        self.listener: socket.socket | None = None
        if not self.linux:
            opened = icmp.open_socket(self.family)
            if opened is None:
                raise OSError("no ICMP socket available to receive router replies")
            self.listener = opened[0]
            self.listener.setblocking(False)

    def __enter__(self) -> TcpTracer:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if self.listener is not None:
            self.listener.close()
            self.listener = None

    def _socket(self, ttl: int) -> socket.socket:
        sock = socket.socket(self.family, socket.SOCK_STREAM)
        try:
            if self.family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_UNICAST_HOPS, ttl)
                if self.linux:
                    sock.setsockopt(socket.IPPROTO_IPV6, getattr(socket, "IPV6_RECVERR", 25), 1)
            else:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
                if self.linux:
                    sock.setsockopt(socket.IPPROTO_IP, getattr(socket, "IP_RECVERR", 11), 1)
            sock.setblocking(False)
        except OSError:
            sock.close()
            raise
        return sock

    def _drain_listener(self) -> None:
        """Drop stale ICMP messages (late answers to earlier probes)."""
        while self.listener is not None:
            try:
                self.listener.recvfrom(2048)
            except (BlockingIOError, InterruptedError, OSError):
                return

    def probe(self, ttl: int, timeout: float = 2.0) -> tuple[str | None, float]:
        """One SYN with hop limit *ttl*: ``(responder, rtt_ms)``, where the
        responder is a router, the destination itself, or None (timeout,
        rtt -1.0)."""
        self._drain_listener()
        sock = self._socket(ttl)
        address = (
            (self.dest_ip, self.port, 0, 0)
            if self.family == socket.AF_INET6
            else (
                self.dest_ip,
                self.port,
            )
        )
        try:
            sent = time.perf_counter()
            code = sock.connect_ex(address)
            local_port = sock.getsockname()[1]
            if code not in _IN_PROGRESS and code not in _REACHED:
                return self._wait_icmp_only(sock, local_port, sent, timeout, code)
            deadline = sent + timeout
            watch_tcp = True
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return None, -1.0
                readers = [self.listener] if self.listener is not None else []
                writers = [sock] if watch_tcp else []
                if not readers and not writers:
                    return None, -1.0
                readable, writable, _ = select.select(readers, writers, [], remaining)
                now = time.perf_counter()
                if writable:
                    err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if err in _REACHED:
                        return self.dest_ip, (now - sent) * 1000
                    router = self._error_queue(sock)
                    if router:
                        return router, (now - sent) * 1000
                    watch_tcp = False  # failed (EHOSTUNREACH …): wait for the ICMP copy
                if readable:
                    router = self._read_listener(local_port)
                    if router:
                        return router, (now - sent) * 1000
                if not watch_tcp and self.listener is None:
                    return None, -1.0
        finally:
            sock.close()

    def _wait_icmp_only(self, sock, local_port, sent, timeout, _code):
        router = self._error_queue(sock)
        if router:
            return router, (time.perf_counter() - sent) * 1000
        deadline = sent + timeout
        while self.listener is not None:
            remaining = deadline - time.perf_counter()
            if remaining <= 0 or not select.select([self.listener], [], [], remaining)[0]:
                break
            router = self._read_listener(local_port)
            if router:
                return router, (time.perf_counter() - sent) * 1000
        return None, -1.0

    def _error_queue(self, sock: socket.socket) -> str | None:
        if not self.linux:
            return None
        try:
            _data, ancdata, _flags, _addr = sock.recvmsg(
                512, 512, getattr(socket, "MSG_ERRQUEUE", 0x2000)
            )
        except (BlockingIOError, OSError):
            return None
        return _offender(ancdata, self.family)

    def _read_listener(self, local_port: int) -> str | None:
        while self.listener is not None:
            try:
                data, addr = self.listener.recvfrom(2048)
            except (BlockingIOError, InterruptedError, OSError):
                return None
            ports = quoted_ports(icmp.strip_ip_header(data, self.family), self.family)
            if ports == (local_port, self.port):
                return addr[0]
        return None
