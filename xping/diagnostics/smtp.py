"""
xping.diagnostics.smtp — is this mail server reachable, and is its TLS
right?

Connects, reads the greeting, sends EHLO, upgrades with STARTTLS (or uses
implicit TLS on port 465), verifies the certificate for the server's
name, and sends EHLO again to see what is offered over TLS (AUTH
mechanisms, size limit). It never sends MAIL FROM — no mail is sent.

Given a mail domain (a name with MX records), the preferred MX server is
tested. Reverse DNS of the server address is checked too: receiving
servers often distrust senders whose PTR name does not resolve back to
the same address.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
import sys
import time

from xping.diagnostics.lookup import query
from xping.diagnostics.resolve import resolve
from xping.diagnostics.sslctx import secure_context
from xping.diagnostics.tls import _format_name
from xping.models.smtp import SmtpResult
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.views import smtp as smtp_view

SMTPS_PORT = 465


def mx_hosts(domain: str) -> list[tuple[int, str]]:
    """MX records sorted by preference; empty when there are none."""
    _status, records, _ms = query(domain, "MX")
    hosts = []
    for record in records:
        prio, _, name = record.partition(" ")
        try:
            hosts.append((int(prio), name.rstrip(".")))
        except ValueError:
            continue
    return sorted(hosts)


def reverse_dns(ip: str) -> tuple[str | None, bool | None]:
    """(PTR name, whether it resolves back to *ip*)."""
    try:
        name = socket.gethostbyaddr(ip)[0]
    except OSError:
        return None, None
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(name, None)}
    except OSError:
        return name, False
    return name, ip in addresses


def _read_cert(result: SmtpResult, sock: ssl.SSLSocket) -> None:
    result.tls_version = sock.version()
    cipher = sock.cipher()
    result.tls_cipher = cipher[0] if cipher else None
    cert = sock.getpeercert() or {}
    result.cert_subject = _format_name(cert.get("subject")) if cert else None
    result.cert_issuer = _format_name(cert.get("issuer")) if cert else None
    result.cert_not_after = cert.get("notAfter")


def _parse_ehlo(result: SmtpResult, client: smtplib.SMTP) -> None:
    features = client.esmtp_features
    result.extensions = sorted(k.upper() for k in features)
    result.auth = sorted(set(features.get("auth", "").upper().split()))
    size = features.get("size", "").strip()
    result.max_size = int(size) if size.isdigit() and int(size) > 0 else None


class _Client(smtplib.SMTP):
    """smtplib connecting to a resolved address while keeping the name for
    TLS, and timing the TCP connect."""

    def __init__(self, ip: str, timeout: float):
        self._ip = ip
        self.connect_ms: float | None = None
        super().__init__(timeout=timeout)

    def _get_socket(self, host, port, timeout):
        started = time.perf_counter()
        sock = socket.create_connection((self._ip, port), timeout)
        self.connect_ms = (time.perf_counter() - started) * 1000
        return sock


class _SslClient(smtplib.SMTP_SSL):
    def __init__(self, ip: str, server: str, timeout: float, context: ssl.SSLContext):
        self._ip, self._server = ip, server
        self.connect_ms: float | None = None
        super().__init__(timeout=timeout, context=context)

    def _get_socket(self, host, port, timeout):
        started = time.perf_counter()
        raw = socket.create_connection((self._ip, port), timeout)
        self.connect_ms = (time.perf_counter() - started) * 1000
        return self.context.wrap_socket(raw, server_hostname=self._server)


def _session(result: SmtpResult, server: str, timeout: float) -> None:
    context = secure_context()
    if result.port == SMTPS_PORT:
        result.implicit_tls = True
        started = time.perf_counter()
        try:
            client = _SslClient(result.ip, server, timeout, context)
            code, banner = client.connect(server, result.port)
        except ssl.SSLCertVerificationError as exc:
            result.cert_error = exc.verify_message or str(exc)
            result.error = f"TLS certificate rejected: {result.cert_error}"
            return
        result.tls_ms = (time.perf_counter() - started) * 1000
        _read_cert(result, client.sock)
    else:
        client = _Client(result.ip, timeout)
        client._host = server  # starttls() takes the TLS server name from here
        code, banner = client.connect(server, result.port)
    result.connect_ms = client.connect_ms
    result.banner_code = code
    result.banner = banner.decode("utf-8", "replace").strip() if banner else None
    try:
        if code != 220:
            return
        client.ehlo()
        _parse_ehlo(result, client)
        if not result.implicit_tls:
            result.starttls_offered = client.has_extn("starttls")
            if result.starttls_offered:
                started = time.perf_counter()
                try:
                    client.starttls(context=context)
                except ssl.SSLCertVerificationError as exc:
                    result.cert_error = exc.verify_message or str(exc)
                    return
                except (ssl.SSLError, smtplib.SMTPException) as exc:
                    result.cert_error = f"STARTTLS failed: {exc}"
                    return
                result.tls_ms = (time.perf_counter() - started) * 1000
                _read_cert(result, client.sock)
                client.ehlo()
                _parse_ehlo(result, client)
    finally:
        try:
            client.quit()
        except (smtplib.SMTPException, OSError):
            client.close()


def smtp(
    host: str,
    port: int = 25,
    timeout: float = 10.0,
    use_mx: bool = True,
    quiet: bool = False,
    family: int | None = None,
) -> SmtpResult:
    host = host.strip().rstrip(".")
    result = SmtpResult(host=host, port=port)
    server = host
    if use_mx:
        records = mx_hosts(host)
        result.mx_hosts = [f"{prio} {name}" for prio, name in records]
        if records and records[0][1] != host:
            server = records[0][1]
    result.server = server

    if not quiet:
        print(section_header(f"SMTP  {server}:{port}", "✉"))
        print(kv("Server", c(server, BRAND_TEAL, BOLD)))
        if server != host:
            print(kv("Mail domain", f"{host}  (preferred MX)"))

    try:
        result.ip = resolve(server, family)
    except socket.gaierror:
        result.error = f"cannot resolve '{server}'"
        if not quiet:
            smtp_view.print_result(result)
        return result

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Talking to the mail server…", BRAND_TEAL))
        spinner.start()
    try:
        result.reverse_dns, result.forward_confirmed = reverse_dns(result.ip)
        _session(result, server, timeout)
    except (TimeoutError, socket.timeout):
        result.error = f"no answer on port {port} (timed out)"
    except ConnectionRefusedError:
        result.error = f"connection refused on port {port}"
    except smtplib.SMTPServerDisconnected as exc:
        result.error = (
            f"server closed the connection: {exc}" if str(exc) else "server closed the connection"
        )
    except (smtplib.SMTPException, OSError) as exc:
        result.error = str(exc) or type(exc).__name__
    finally:
        if spinner:
            spinner.stop()

    if not quiet:
        smtp_view.print_result(result)
    return result
