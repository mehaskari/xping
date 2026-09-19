"""
xping.portscan — Live TCP port scanner with service banner grabbing.
"""

import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from xping.models.portscan import PortResult, PortScanResult
from xping.render import BOLD, BRAND_INDIGO, BRAND_MINT, BRAND_TEAL, c, kv, section_header
from xping.render.errors import resolve_error
from xping.render.views import portscan as portscan_view


def parse_ports(value: str) -> list[int]:
    ports: set[int] = set()
    for chunk in value.split(","):
        part = chunk.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = _parse_port(start_s), _parse_port(end_s)
            if start > end:
                raise ValueError("port ranges must be ascending")
            ports.update(range(start, end + 1))
        else:
            ports.add(_parse_port(part))
    if not ports:
        raise ValueError("at least one port is required")
    return sorted(ports)


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"invalid port: {value}") from exc
    if not 1 <= port <= 65535:
        raise ValueError("ports must be between 1 and 65535")
    return port


def _service_name(port: int) -> str | None:
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return None


# Service-specific probes to trigger banner responses
_PROBES: dict[int, bytes] = {
    80: b"HEAD / HTTP/1.0\r\nHost: x\r\n\r\n",
    8080: b"HEAD / HTTP/1.0\r\nHost: x\r\n\r\n",
    8443: b"",
    443: b"",  # TLS — read first bytes
    22: b"",  # SSH sends banner on connect
    21: b"",  # FTP
    25: b"",  # SMTP
    110: b"",  # POP3
    143: b"",  # IMAP
    3306: b"",  # MySQL
    5432: b"",  # PostgreSQL
    6379: b"",  # Redis
    27017: b"",  # MongoDB
}

_FINGERPRINTS: list[tuple[bytes, str]] = [
    (b"SSH-2.0", "SSH"),
    (b"SSH-1.", "SSH"),
    (b"220 ", "FTP/SMTP"),
    (b"HTTP/1.", "HTTP"),
    (b"+OK", "POP3"),
    (b"* OK", "IMAP"),
    (b"\xff\xfb", "Telnet"),
    (b"-ERR", "Redis"),
    (b"+PONG", "Redis"),
    (b"\x16\x03", "TLS"),
    (b"\x15\x03", "TLS"),
    (b"5.", "MySQL"),
    (b"8.", "MySQL"),
    (b"PostgreSQL", "PostgreSQL"),
]


def _grab_banner(ip: str, port: int, timeout: float = 1.5) -> str | None:
    probe = _PROBES.get(port, b"")
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            if probe:
                sock.sendall(probe)
            try:
                raw = sock.recv(256)
            except (socket.timeout, OSError):
                return None
        if not raw:
            return None
        for sig, name in _FINGERPRINTS:
            if raw[: len(sig)] == sig:
                line = raw.split(b"\n")[0].decode("ascii", errors="replace").strip()
                return f"{name}: {line[:60]}" if line else name
        text = raw[:80].decode("ascii", errors="replace").split("\n")[0].strip()
        printable = all(c >= " " or c == "\t" for c in text)
        if text and printable:
            return text[:60]
        return f"binary ({len(raw)} bytes)"
    except Exception:
        return None


def scan_port(ip: str, port: int, timeout: float, grab_banners: bool = False) -> PortResult:
    started = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            elapsed_ms = (time.perf_counter() - started) * 1000
            banner = _grab_banner(ip, port) if grab_banners else None
            return PortResult(
                port=port,
                open=True,
                elapsed_ms=elapsed_ms,
                service=_service_name(port),
                banner=banner,
            )
    except TimeoutError:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return PortResult(
            port=port,
            open=False,
            elapsed_ms=elapsed_ms,
            service=_service_name(port),
            error="timeout",
        )
    except OSError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return PortResult(
            port=port,
            open=False,
            elapsed_ms=elapsed_ms,
            service=_service_name(port),
            error=str(exc),
        )


def portscan(
    host: str,
    ports: list[int],
    timeout: float = 0.5,
    workers: int = 100,
    grab_banners: bool = False,
    quiet: bool = False,
) -> PortScanResult:
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror as exc:
        if not quiet:
            resolve_error(host, exc)
        return PortScanResult(host=host, ip="?", ports=ports, resolved=False, error=str(exc))

    if not quiet:
        print(section_header(f"PORT SCAN  {host}", "▦"))
        print(kv("Target", c(host, BRAND_TEAL, BOLD)))
        print(kv("IP", c(ip, BRAND_INDIGO)))
        print(kv("Ports", f"{len(ports)} total"))
        print(kv("Timeout", f"{timeout}s / port"))
        if grab_banners:
            print(kv("Banners", c("enabled", BRAND_MINT)))
        print()

    results: list[PortResult] = []
    max_workers = max(1, min(workers, len(ports)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(scan_port, ip, port, timeout, grab_banners): port for port in ports
        }
        for future in as_completed(futures):
            item = future.result()
            results.append(item)
            if not quiet:
                portscan_view.print_port_result(item)

    results.sort(key=lambda item: item.port)
    scan_result = PortScanResult(host=host, ip=ip, ports=ports, results=results)
    if not quiet:
        portscan_view.print_summary(scan_result)
    return scan_result
