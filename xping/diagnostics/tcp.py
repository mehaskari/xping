"""
xping.tcp - Live TCP connectivity diagnostics.
"""

import socket
import time

from xping.models.tcp import TcpAttempt, TcpResult
from xping.render import c, section_header, kv, BRAND_TEAL, BRAND_INDIGO, BOLD
from xping.render.errors import resolve_error
from xping.render.views import tcp as tcp_view


def _resolve(host: str, port: int, timeout: float) -> str:
    infos = socket.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    for family, _, _, _, sockaddr in infos:
        if family in (socket.AF_INET, socket.AF_INET6):
            return sockaddr[0]
    raise socket.gaierror(f"no TCP address found for {host}")


def _connect_once(host: str, port: int, timeout: float, seq: int) -> TcpAttempt:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed_ms = (time.perf_counter() - started) * 1000
            return TcpAttempt(seq=seq, ok=True, elapsed_ms=elapsed_ms)
    except TimeoutError:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return TcpAttempt(seq=seq, ok=False, elapsed_ms=elapsed_ms, error="timeout")
    except OSError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return TcpAttempt(seq=seq, ok=False, elapsed_ms=elapsed_ms, error=str(exc))


def tcp(host: str, port: int, count: int = 3, timeout: float = 2.0,
        interval: float = 0.5, quiet: bool = False) -> TcpResult:
    try:
        ip = _resolve(host, port, timeout)
    except socket.gaierror as exc:
        if not quiet:
            resolve_error(host, exc)
        return TcpResult(host=host, port=port, ip="?", resolved=False, error=str(exc))

    if not quiet:
        print(section_header(f"TCP CONNECT  {host}:{port}", "◍"))
        print(kv("Target", c(host, BRAND_TEAL, BOLD)))
        print(kv("Port", c(str(port), BRAND_INDIGO)))
        print(kv("IP", c(ip, BRAND_INDIGO)))
        print(kv("Attempts", str(count)))
        print(kv("Timeout", f"{timeout}s / attempt"))
        print()

    attempts: list[TcpAttempt] = []
    for seq in range(1, count + 1):
        started = time.perf_counter()
        attempt = _connect_once(host, port, timeout, seq)
        attempts.append(attempt)
        if not quiet:
            tcp_view.print_line(attempt, count)

        if seq < count:
            remaining = interval - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)

    result = TcpResult(host=host, port=port, ip=ip, attempts=attempts)
    if not quiet:
        tcp_view.print_summary(result)
    return result
