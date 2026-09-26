"""
xping.diagnostics.http — HTTP diagnostics with HTTP/2 detection and timing breakdown.

DNS · TCP connect · TLS handshake · server response (TTFB) · download —
each measured separately, like ``curl -w``. The final response's headers
are also audited for the common security headers.
"""

import http.client
import re
import socket
import ssl
import sys
import time
from urllib.parse import urljoin, urlsplit

from xping.diagnostics.resolve import resolve
from xping.diagnostics.sslctx import secure_context as _ssl_context
from xping.models.http import HttpResult, RedirectHop, SecurityHeader
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.errors import error, resolve_error
from xping.render.views import http as http_view

MAX_REDIRECTS = 10
HSTS_MIN_AGE = 180 * 24 * 3600  # what hstspreload.org and most scanners ask for


def audit_headers(start_url: str, final_url: str, headers: dict[str, str]) -> list[SecurityHeader]:
    """Check the final response for the usual security headers.

    Informational only — it never changes the exit code. Header names are
    matched case-insensitively."""
    h = {k.lower(): v for k, v in headers.items()}
    https = urlsplit(final_url).scheme == "https"
    items: list[SecurityHeader] = []

    if https and urlsplit(start_url).scheme == "http":
        items.append(SecurityHeader("HTTPS", "ok", None, "http:// redirects to https://"))
    elif https:
        items.append(SecurityHeader("HTTPS", "ok", None, "served over TLS"))
    else:
        items.append(SecurityHeader("HTTPS", "warn", None, "served over plain HTTP"))

    hsts = h.get("strict-transport-security")
    if not https:
        pass  # browsers ignore HSTS on plain HTTP; the HTTPS row already warns
    elif hsts is None:
        items.append(SecurityHeader("Strict-Transport-Security", "missing", None, "no HSTS"))
    else:
        m = re.search(r"max-age\s*=\s*\"?(\d+)", hsts, re.I)
        age = int(m.group(1)) if m else 0
        if age < HSTS_MIN_AGE:
            items.append(
                SecurityHeader("Strict-Transport-Security", "warn", hsts, "max-age under 180 days")
            )
        else:
            items.append(SecurityHeader("Strict-Transport-Security", "ok", hsts, ""))

    csp = h.get("content-security-policy")
    items.append(
        SecurityHeader("Content-Security-Policy", "ok", csp, "")
        if csp
        else SecurityHeader("Content-Security-Policy", "missing", None, "no CSP")
    )

    xcto = h.get("x-content-type-options")
    if xcto and xcto.strip().lower() == "nosniff":
        items.append(SecurityHeader("X-Content-Type-Options", "ok", xcto, ""))
    else:
        items.append(SecurityHeader("X-Content-Type-Options", "missing", xcto, "should be nosniff"))

    xfo = h.get("x-frame-options")
    if xfo:
        items.append(SecurityHeader("X-Frame-Options", "ok", xfo, ""))
    elif csp and "frame-ancestors" in csp.lower():
        items.append(
            SecurityHeader("X-Frame-Options", "ok", None, "covered by CSP frame-ancestors")
        )
    else:
        items.append(SecurityHeader("X-Frame-Options", "missing", None, "clickjacking protection"))

    for name in ("Referrer-Policy", "Permissions-Policy"):
        value = h.get(name.lower())
        items.append(
            SecurityHeader(name, "ok", value, "")
            if value
            else SecurityHeader(name, "missing", None, "")
        )

    for name in ("Server", "X-Powered-By"):
        value = h.get(name.lower())
        if value and re.search(r"\d+\.\d+", value):
            items.append(SecurityHeader(name, "warn", value, "reveals software version"))
    return items


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


def _one_request(url: str, timeout: float, family: int | None = None) -> dict:
    """Issue a single GET and return a timing + metadata dict.

    The connection is built by hand — TCP connect, then the TLS handshake —
    so each phase is timed on its own instead of TCP including TLS."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme '{parts.scheme}'")
    host = parts.hostname
    if not host:
        raise ValueError("URL is missing a host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    is_https = parts.scheme == "https"

    t0 = time.perf_counter()
    ip = resolve(host, family)
    dns_ms = (time.perf_counter() - t0) * 1000

    # TCP connect to the address resolved above (honours -4/-6), while
    # *host* stays in the Host header and TLS SNI/certificate checks.
    t1 = time.perf_counter()
    sock = socket.create_connection((ip, port), timeout=timeout)
    tcp_ms = (time.perf_counter() - t1) * 1000

    tls_ms = tls_version = tls_cipher = None
    try:
        if is_https:
            # Only HTTP/1.1 is offered via ALPN: http.client cannot speak
            # HTTP/2, so letting the server pick "h2" here would make it
            # reject our HTTP/1.1 request as a malformed h2 preface.
            ctx = _ssl_context()
            ctx.set_alpn_protocols(["http/1.1"])
            t_tls = time.perf_counter()
            sock = ctx.wrap_socket(sock, server_hostname=host)
            tls_ms = (time.perf_counter() - t_tls) * 1000
            tls_version = sock.version()
            cipher = sock.cipher()
            tls_cipher = cipher[0] if cipher else None
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = sock  # already connected: request() will not reconnect
    except BaseException:
        sock.close()
        raise

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
        t3 = time.perf_counter()
        body = resp.read()
        t4 = time.perf_counter()
        return dict(
            status=resp.status,
            reason=resp.reason,
            headers=dict(resp.getheaders()),
            location=resp.getheader("Location"),
            body_bytes=len(body),
            dns_ms=dns_ms,
            tcp_ms=tcp_ms,
            tls_ms=tls_ms,
            ttfb_ms=(t3 - t2) * 1000,
            transfer_ms=(t4 - t3) * 1000,
            total_ms=(t4 - t0) * 1000,
            http_version="HTTP/1.0" if resp.version == 10 else "HTTP/1.1",
            tls_version=tls_version,
            tls_cipher=tls_cipher,
            ip=ip,
        )
    finally:
        conn.close()


def http_diagnose(
    url: str, timeout: float = 8.0, quiet: bool = False, family: int | None = None
) -> HttpResult:
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
        resolve(host, family)
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

            d = _one_request(current, timeout, family)

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
            result.redirect_ms = result.total_ms - d["total_ms"] if result.redirects else None
            result.dns_ms = d["dns_ms"]
            result.tcp_ms = d["tcp_ms"]
            result.tls_ms = d["tls_ms"]
            result.transfer_ms = d["transfer_ms"]
            result.http_version = d["http_version"]
            result.tls_version = d["tls_version"]
            result.tls_cipher = d["tls_cipher"]
            result.ip = d.get("ip")
            result.security = audit_headers(url, current, result.headers)
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
