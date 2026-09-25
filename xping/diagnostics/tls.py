"""
xping.diagnostics.tls — TLS/SSL certificate inspector.
Performs a real TLS handshake against the target and reports the
negotiated protocol, cipher, and certificate details.
"""

import socket
import ssl
import sys

from xping.diagnostics.sslctx import secure_context
from xping.models.tls import TlsResult
from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.errors import error, resolve_error
from xping.render.views import tls as tls_view


def _format_name(name_tuples) -> str:
    if not name_tuples:
        return "?"
    parts = []
    for rdn in name_tuples:
        for key, value in rdn:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def tls(host: str, port: int = 443, timeout: float = 5.0, quiet: bool = False) -> TlsResult:
    """Connect to *host*:*port*, perform a TLS handshake, and report cert info."""
    result = TlsResult(host=host, port=port)

    try:
        ip = socket.gethostbyname(host)
        result.ip = ip
    except socket.gaierror:
        if not quiet:
            resolve_error(host)
        result.error = f"Cannot resolve '{host}'"
        return result

    if not quiet:
        print(section_header(f"TLS INSPECTOR  {host}:{port}", "◒"))
        print(kv("Target", c(f"{host}:{port}", BRAND_TEAL, BOLD)))
        print(kv("IP", c(ip, BRAND_INDIGO)))
        print()

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Negotiating TLS handshake…", BRAND_TEAL))
        spinner.start()

    context = secure_context()

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                cert = tls_sock.getpeercert()
                cipher = tls_sock.cipher()
                result.protocol = tls_sock.version()
                if cipher:
                    result.cipher = cipher[0]
                if cert:
                    result.subject = _format_name(cert.get("subject"))
                    result.issuer = _format_name(cert.get("issuer"))
                    result.not_before = cert.get("notBefore")
                    result.not_after = cert.get("notAfter")
                    result.san = [
                        value for key, value in cert.get("subjectAltName", ()) if key == "DNS"
                    ]
                # Certificate chain — Python 3.13+ exposes get_verified_chain()
                # On older versions we parse the DER chain manually
                chain_names: list[str] = []
                try:
                    chain = tls_sock.get_verified_chain()  # type: ignore[attr-defined]
                    for c_obj in chain:
                        subj = c_obj.get_subject()
                        chain_names.append(getattr(subj, "CN", None) or "?")
                except AttributeError:
                    # Fallback: issuer chain from the leaf cert
                    if result.subject:
                        chain_names.append(result.subject.split("CN=")[-1].split(",")[0])
                    if result.issuer and result.issuer != result.subject:
                        chain_names.append(result.issuer.split("CN=")[-1].split(",")[0])
                result.chain = chain_names
    except ssl.SSLCertVerificationError as exc:
        result.error = f"Certificate verification failed: {exc.verify_message}"
    except ssl.SSLError as exc:
        result.error = f"TLS handshake failed: {exc}"
    except (socket.timeout, TimeoutError):
        result.error = "Connection timed out"
    except ConnectionRefusedError:
        result.error = f"Connection refused on port {port}"
    except OSError as exc:
        result.error = str(exc)
    finally:
        if spinner:
            spinner.stop()

    if not quiet:
        if result.error:
            error(result.error)
        else:
            tls_view.print_result(result)
    return result
