"""
xping.diagnostics.speedtest — Download speed measurement.
Uses Cloudflare's public speed endpoint and icanhazip for a quick
single-connection throughput estimate. Pure stdlib, no iperf3 needed.
"""

import http.client
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from xping.diagnostics.sslctx import secure_context
from xping.models.speedtest import SpeedResult
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.errors import error
from xping.render.views import speedtest as speedtest_view

_PING_URL = "https://speed.cloudflare.com/cdn-cgi/trace"
_DOWN_URL = "https://speed.cloudflare.com/__down?bytes={size}"
_UP_URL = "https://speed.cloudflare.com/__up"
# Per-stream download sizes. speed.cloudflare.com answers 403 for some sizes
# (observed: everything tried between 11 and 19 MB), so stick to sizes it
# serves: 25 MB per stream for 1-2 streams, 10 MB for more (4 streams = 40 MB).
# Streams also stop early once --duration is reached.
_DOWN_LARGE, _DOWN_SMALL = 25_000_000, 10_000_000
_UPLOAD_TOTAL = 8_000_000  # split across the connections
_CHUNK = 65536


def _measure_ping(timeout: float = 5.0) -> tuple[float | None, str | None]:
    """Best of 3 HTTPS round trips, plus the Cloudflare colo that answered."""
    ctx = secure_context()
    times = []
    colo = None
    for _ in range(3):
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(_PING_URL, context=ctx, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            times.append((time.perf_counter() - t0) * 1000)
            colo = colo or next(
                (line.split("=", 1)[1] for line in body.splitlines() if line.startswith("colo=")),
                None,
            )
        except Exception:
            continue  # one failed sample is fine; the fastest successful one is reported
    return (min(times) if times else None), colo


def _measure_download(
    connections: int = 4, duration: float = 8.0, timeout: float = 20.0
) -> tuple[float | None, int, str | None]:
    """Parallel download for up to *duration* seconds.

    Returns (Mbps, bytes, error). Throughput is measured from the first
    received byte, so connection and TLS setup don't drag the result down.
    """
    ctx = secure_context()
    lock = threading.Lock()
    state = {"bytes": 0, "first": None, "last": None, "errors": []}
    deadline = time.perf_counter() + duration + 3  # allow for setup

    size = _DOWN_LARGE if connections <= 2 else _DOWN_SMALL

    def open_stream():
        for attempt_size in dict.fromkeys((size, _DOWN_SMALL)):
            req = urllib.request.Request(
                _DOWN_URL.format(size=attempt_size), headers={"User-Agent": "xping/speedtest"}
            )
            try:
                return urllib.request.urlopen(req, context=ctx, timeout=timeout)
            except urllib.error.HTTPError as exc:
                if exc.code != 403 or attempt_size == _DOWN_SMALL:
                    raise
        raise RuntimeError("no download size accepted")

    def stream() -> None:
        try:
            with open_stream() as r:
                while True:
                    chunk = r.read(_CHUNK)
                    now = time.perf_counter()
                    if not chunk:
                        break
                    with lock:
                        state["first"] = state["first"] or now
                        state["last"] = now
                        state["bytes"] += len(chunk)
                        if now - state["first"] >= duration or now >= deadline:
                            break
        except Exception as exc:
            with lock:
                state["errors"].append(str(exc))

    threads = [threading.Thread(target=stream, daemon=True) for _ in range(connections)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + duration)

    total, first, last = state["bytes"], state["first"], state["last"]
    if not total or first is None or last is None or last <= first:
        return None, total, state["errors"][0] if state["errors"] else "no data received"
    return (total * 8) / (last - first) / 1_000_000, total, None


def _measure_upload(connections: int = 4, timeout: float = 20.0) -> tuple[float | None, int]:
    """Parallel upload of _UPLOAD_TOTAL bytes. Returns (Mbps, bytes sent).

    Every connection completes its TLS handshake first; timing starts at a
    barrier just before the bodies are sent, so setup cost is excluded.
    """
    size = max(_UPLOAD_TOTAL // connections, _CHUNK)
    payload = b"x" * size
    host = urllib.parse.urlsplit(_UP_URL).hostname or "speed.cloudflare.com"
    barrier = threading.Barrier(connections, timeout=timeout)
    lock = threading.Lock()
    spans: list[tuple[float, float]] = []

    def push() -> None:
        conn = http.client.HTTPSConnection(host, timeout=timeout, context=secure_context())
        try:
            conn.connect()
        except OSError:
            barrier.abort()
            return
        try:
            barrier.wait()
            started = time.perf_counter()
            conn.request(
                "POST",
                "/__up",
                body=payload,
                headers={
                    "Content-Type": "application/octet-stream",
                    "User-Agent": "xping/speedtest",
                },
            )
            conn.getresponse().read()
            with lock:
                spans.append((started, time.perf_counter()))
        except (OSError, threading.BrokenBarrierError, http.client.HTTPException):
            return  # a failed stream simply doesn't count toward the total
        finally:
            conn.close()

    threads = [threading.Thread(target=push, daemon=True) for _ in range(connections)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout * 2)
    if not spans:
        return None, 0
    sent = size * len(spans)
    elapsed = max(end for _, end in spans) - min(start for start, _ in spans)
    return ((sent * 8) / elapsed / 1_000_000 if elapsed > 0 else None), sent


def speedtest(connections: int = 4, duration: float = 8.0, quiet: bool = False) -> SpeedResult:
    """Measure download speed, upload speed, and ping via Cloudflare."""
    result = SpeedResult(connections=connections)

    if not quiet:
        print(section_header("SPEED TEST", "◈"))
        print(kv("Server", c("speed.cloudflare.com", BRAND_TEAL, BOLD)))
        plural = "s" if connections != 1 else ""
        print(
            kv(
                "Method",
                f"HTTPS, {connections} parallel connection{plural}, ≤{duration:g}s download",
            )
        )
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
    result.ping_ms, colo = _measure_ping()
    result.server = f"speed.cloudflare.com ({colo})" if colo else "speed.cloudflare.com"
    if spinner:
        spinner.stop()
        spinner = None
    if not quiet and result.ping_ms:
        print(kv("Ping", f"{result.ping_ms:.1f} ms"))

    # Download
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c(f"Measuring download ({connections} streams)…", BRAND_TEAL))
        spinner.start()
    dl, result.download_bytes, dl_error = _measure_download(connections, duration)
    result.download_mbps = dl
    if dl is None:
        result.error = f"Download failed: {dl_error}"
    if spinner:
        spinner.stop()
        spinner = None
    if not quiet and dl:
        from xping.render import BRAND_AMBER, BRAND_MINT, BRAND_ROSE

        dl_color = BRAND_MINT if dl >= 25 else BRAND_AMBER if dl >= 5 else BRAND_ROSE
        print(kv("Download", c(f"{dl:.1f} Mbps", dl_color, BOLD)))

    # Upload
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c(f"Measuring upload ({connections} streams)…", BRAND_TEAL))
        spinner.start()
    result.upload_mbps, result.upload_bytes = _measure_upload(connections)
    if spinner:
        spinner.stop()

    if not quiet:
        speedtest_view.print_result(result)
    return result
