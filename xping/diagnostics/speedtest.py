"""
xping.diagnostics.speedtest — Download speed measurement.
Uses Cloudflare's public speed endpoint and icanhazip for a quick
single-connection throughput estimate. Pure stdlib, no iperf3 needed.
"""

import socket
import ssl
import sys
import time
import urllib.request

from xping.models.speedtest import SpeedResult
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.errors import error
from xping.render.views import speedtest as speedtest_view

# Cloudflare __down endpoint — returns a fixed-size payload at line speed
_SERVERS = [
    ("Cloudflare", "speed.cloudflare.com", "/cdn-cgi/trace"),
    ("Cloudflare", "speed.cloudflare.com", "/__down?bytes=25000000"),
]
_PING_URL   = "https://speed.cloudflare.com/cdn-cgi/trace"
_DOWN_URL   = "https://speed.cloudflare.com/__down?bytes=25000000"   # 25 MB
_UP_URL     = "https://speed.cloudflare.com/__up"


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi; ctx.load_verify_locations(certifi.where())
    except ImportError: pass
    return ctx


def _measure_ping(timeout: float = 5.0) -> float | None:
    ctx = _ssl_ctx()
    times = []
    for _ in range(3):
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(_PING_URL, context=ctx, timeout=timeout) as r:
                r.read()
            times.append((time.perf_counter() - t0) * 1000)
        except Exception:
            pass
    return min(times) if times else None


def _measure_download(timeout: float = 20.0) -> tuple[float | None, str]:
    ctx = _ssl_ctx()
    try:
        req = urllib.request.Request(_DOWN_URL, headers={"User-Agent": "xping/speedtest"})
        t0 = time.perf_counter()
        total = 0
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                total += len(chunk)
        elapsed = time.perf_counter() - t0
        if elapsed <= 0 or total == 0:
            return None, "speed.cloudflare.com"
        mbps = (total * 8) / elapsed / 1_000_000
        return mbps, "speed.cloudflare.com"
    except Exception as exc:
        return None, str(exc)


def _measure_upload(size_bytes: int = 5_000_000, timeout: float = 20.0) -> float | None:
    ctx = _ssl_ctx()
    payload = b"x" * size_bytes
    try:
        req = urllib.request.Request(
            _UP_URL, data=payload, method="POST",
            headers={"Content-Type": "application/octet-stream",
                     "User-Agent": "xping/speedtest"}
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            r.read()
        elapsed = time.perf_counter() - t0
        if elapsed <= 0:
            return None
        return (size_bytes * 8) / elapsed / 1_000_000
    except Exception:
        return None


def speedtest(quiet: bool = False) -> SpeedResult:
    """Measure download speed, upload speed, and ping via Cloudflare."""
    result = SpeedResult()

    if not quiet:
        print(section_header("SPEED TEST", "◈"))
        print(kv("Server", c("speed.cloudflare.com", BRAND_TEAL, BOLD)))
        print(kv("Method", "HTTP single-connection (25 MB down, 5 MB up)"))
        print()

    # Connectivity check
    try:
        socket.gethostbyname("speed.cloudflare.com")
    except socket.gaierror:
        result.error = "Cannot reach speed.cloudflare.com — check connectivity"
        if not quiet:
            error(result.error)
        return result

    spinner = None

    # Ping
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Measuring latency…", BRAND_TEAL))
        spinner.start()
    result.ping_ms = _measure_ping()
    if spinner: spinner.stop(); spinner = None
    if not quiet and result.ping_ms:
        print(kv("Ping", f"{result.ping_ms:.1f} ms"))

    # Download
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Measuring download (25 MB)…", BRAND_TEAL))
        spinner.start()
    dl, server = _measure_download()
    result.download_mbps = dl
    result.server = server
    if spinner: spinner.stop(); spinner = None
    if not quiet and dl:
        from xping.render import BRAND_MINT, BRAND_AMBER, BRAND_ROSE, DIM
        dl_color = BRAND_MINT if dl >= 25 else BRAND_AMBER if dl >= 5 else BRAND_ROSE
        print(kv("Download", c(f"{dl:.1f} Mbps", dl_color, BOLD)))

    # Upload
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Measuring upload (5 MB)…", BRAND_TEAL))
        spinner.start()
    ul = _measure_upload()
    result.upload_mbps = ul
    if spinner: spinner.stop(); spinner = None

    if not quiet:
        speedtest_view.print_result(result)
    return result
