"""
xping.diagnostics.http — HTTP diagnostics with HTTP/2 detection and timing breakdown.
DNS · TCP connect · TTFB · Total — each measured separately.
"""

import http.client
import socket
import ssl
import sys
import time
from urllib.parse import urljoin, urlsplit

from xping.diagnostics.sslctx import secure_context as _ssl_context
from xping.models.http import HttpResult, RedirectHop
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.errors import error, resolve_error
from xping.render.views import http as http_view

MAX_REDIRECTS = 10


def _supports_h2(host: str, port: int, timeout: float) -> bool | None:
    """Separate ALPN-only handshake: does the server offer HTTP/2?

    Returns None when the probe itself fails (the main request already
    succeeded, so this is informational only)."""
    ctx = _ssl_context()
    ctx.set_alpn_protocols(["h2", "http/1.1"])
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls_sock:
                return tls_sock.selected_alpn_protocol() == "h2"
    except (OSError, ssl.SSLError):
        return None


def _one_request(url: str, timeout: float) -> dict:
    """Issue a single GET and return a timing + metadata dict."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme '{parts.scheme}'")
    host = parts.hostname
    if not host:
        raise ValueError("URL is missing a host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    is_https = parts.scheme == "https"

    # DNS time
    t0 = time.perf_counter()
    socket.gethostbyname(host)
    dns_ms = (time.perf_counter() - t0) * 1000

    # TCP connect + optional TLS. Only HTTP/1.1 is offered via ALPN:
    # http.client cannot speak HTTP/2, so letting the server pick "h2" here
    # would make it reject our HTTP/1.1 request as a malformed h2 preface.
    t1 = time.perf_counter()
    if is_https:
        ctx = _ssl_context()
        ctx.set_alpn_protocols(["http/1.1"])
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.connect()
    tcp_ms = (time.perf_counter() - t1) * 1000

    try:
        t2 = time.perf_counter()
        conn.request(
            "GET",
            path,
            headers={
                "User-Agent": "xping/http-diagnostics",
                "Accept": "*/*",
                "Connection": "close",
            },
        )
        resp = conn.getresponse()
        ttfb_ms = (time.perf_counter() - t2) * 1000
        body = resp.read()
        http_version = "HTTP/1.0" if resp.version == 10 else "HTTP/1.1"
        total_ms = (time.perf_counter() - t1) * 1000
        return dict(
            status=resp.status,
            reason=resp.reason,
            headers=dict(resp.getheaders()),
            location=resp.getheader("Location"),
            body_bytes=len(body),
            dns_ms=dns_ms,
            tcp_ms=tcp_ms,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            http_version=http_version,
        )
    finally:
        conn.close()


def http_diagnose(url: str, timeout: float = 8.0, quiet: bool = False) -> HttpResult:
    if "://" not in url:
        url = f"http://{url}"

    result = HttpResult(url=url)
    host = urlsplit(url).hostname

    if not host:
        result.error = "URL is missing a host"
        if not quiet:
            error(result.error)
        return result

    try:
        socket.gethostbyname(host)
    except socket.gaierror:
        if not quiet:
            resolve_error(host)
        result.error = f"Cannot resolve '{host}'"
        return result

    if not quiet:
        print(section_header(f"HTTP DIAGNOSTICS  {url}", "◓"))
        print(kv("URL", c(url, BRAND_TEAL, BOLD)))
        print()

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Requesting…", BRAND_TEAL))
        spinner.start()

    current = url
    seen: set[str] = set()
    total_wall = time.perf_counter()

    try:
        for _ in range(MAX_REDIRECTS + 1):
            if current in seen:
                result.error = "Redirect loop detected"
                break
            seen.add(current)

            d = _one_request(current, timeout)

            if 300 <= d["status"] < 400 and d["location"]:
                result.redirects.append(RedirectHop(url=current, status_code=d["status"]))
                current = urljoin(current, d["location"])
                continue

            result.final_url = current
            result.status_code = d["status"]
            result.reason = d["reason"]
            result.headers = d["headers"]
            result.body_bytes = d["body_bytes"]
            result.ttfb_ms = d["ttfb_ms"]
            result.total_ms = (time.perf_counter() - total_wall) * 1000
            result.dns_ms = d["dns_ms"]
            result.tcp_ms = d["tcp_ms"]
            result.http_version = d["http_version"]
            final = urlsplit(current)
            if final.scheme == "https" and final.hostname:
                result.h2_supported = _supports_h2(final.hostname, final.port or 443, timeout)
            break
        else:
            result.error = f"Too many redirects (> {MAX_REDIRECTS})"
    except (socket.timeout, TimeoutError):
        result.error = "Request timed out"
    except ConnectionRefusedError:
        result.error = "Connection refused"
    except ssl.SSLError as exc:
        result.error = f"TLS error: {exc}"
    except (OSError, ValueError, http.client.HTTPException) as exc:
        result.error = str(exc)
    finally:
        if spinner:
            spinner.stop()

    if not quiet:
        if result.error:
            error(result.error)
        else:
            http_view.print_result(result)
    return result
