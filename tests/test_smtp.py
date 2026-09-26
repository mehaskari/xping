"""xping smtp — against a local fake SMTP server (no TLS) plus mocked TLS paths."""

import json
import socket
import ssl
import threading
from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.cli.verdict import evaluate
from xping.diagnostics import smtp as sm
from xping.exporters.json import export_json
from xping.models.smtp import SmtpResult

REAL_REVERSE_DNS = sm.reverse_dns  # before the autouse fixture replaces it


def _server(greeting=b"220 mail.test ESMTP ready", ehlo_lines=None):
    """A one-connection fake SMTP server; returns (port, transcript)."""
    ehlo_lines = ehlo_lines or [b"250-mail.test", b"250-SIZE 10485760", b"250-AUTH PLAIN LOGIN", b"250 8BITMIME"]
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    transcript = []

    def serve():
        conn, _ = listener.accept()
        with conn, conn.makefile("rwb") as f:
            f.write(greeting + b"\r\n")
            f.flush()
            for line in f:
                command = line.strip().upper()
                transcript.append(command)
                if command.startswith(b"EHLO"):
                    f.write(b"\r\n".join(ehlo_lines) + b"\r\n")
                elif command == b"QUIT":
                    f.write(b"221 bye\r\n")
                    f.flush()
                    break
                else:
                    f.write(b"502 no\r\n")
                f.flush()
        listener.close()

    threading.Thread(target=serve, daemon=True).start()
    return listener.getsockname()[1], transcript


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    monkeypatch.setattr(sm, "mx_hosts", lambda domain: [])
    monkeypatch.setattr(sm, "reverse_dns", lambda ip: ("mail.test", True))


def test_plain_server_without_starttls():
    port, transcript = _server()
    result = sm.smtp("127.0.0.1", port=port, timeout=3, quiet=True)
    assert result.banner_code == 220 and result.banner == "mail.test ESMTP ready"
    assert result.starttls_offered is False and not result.tls
    assert result.auth == ["LOGIN", "PLAIN"] and result.max_size == 10485760
    assert "8BITMIME" in result.extensions and result.connect_ms is not None
    assert transcript[-1] == b"QUIT" and not any(c.startswith(b"MAIL") for c in transcript)  # no mail sent
    assert evaluate(result) == []
    required = evaluate(result, type("O", (), {"require_tls": True})())
    assert required and "offers no TLS" in required[0].message


def test_refused_greeting():
    port, _ = _server(greeting=b"554 go away")
    result = sm.smtp("127.0.0.1", port=port, timeout=3, quiet=True)
    assert result.banner_code == 554 and "refused the session" in evaluate(result)[0].message


def test_connection_refused_and_unresolvable():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    assert "refused" in sm.smtp("127.0.0.1", port=port, timeout=2, quiet=True).error
    with patch.object(sm, "resolve", side_effect=socket.gaierror):
        assert sm.smtp("nothing.invalid", quiet=True).error == "cannot resolve 'nothing.invalid'"


def test_mail_domain_uses_preferred_mx(monkeypatch):
    monkeypatch.setattr(sm, "mx_hosts", lambda d: [(10, "mx1.example.net"), (20, "mx2.example.net")])
    with patch.object(sm, "resolve", side_effect=socket.gaierror):
        result = sm.smtp("example.net", quiet=True)
    assert result.server == "mx1.example.net" and result.mx_hosts[1] == "20 mx2.example.net"
    with patch.object(sm, "resolve", side_effect=socket.gaierror):
        assert sm.smtp("example.net", use_mx=False, quiet=True).server == "example.net"


def test_starttls_certificate_failure_is_reported():
    port, _ = _server(ehlo_lines=[b"250-mail.test", b"250 STARTTLS"])
    err = ssl.SSLCertVerificationError("certificate verify failed")
    err.verify_message = "Hostname mismatch, certificate is not valid for '127.0.0.1'."
    with patch("smtplib.SMTP.starttls", side_effect=err):
        result = sm.smtp("127.0.0.1", port=port, timeout=3, quiet=True)
    assert result.starttls_offered and "Hostname mismatch" in result.cert_error
    assert evaluate(result) == []  # common on port 25: a warning, not a failure
    assert "does not verify" in evaluate(result, type("O", (), {"require_tls": True})())[0].message


def test_cert_days_and_min_days():
    r = SmtpResult("h", server="h", banner_code=220, tls_version="TLSv1.3",
                   cert_not_after="Jan  1 00:00:00 2000 GMT")
    assert r.cert_days < 0
    assert "expires in" in evaluate(r, type("O", (), {"min_days": 14})())[0].message
    assert json.loads(export_json(r))["tls"] is True


def test_reverse_dns_forward_confirmation():
    real = REAL_REVERSE_DNS
    with (
        patch.object(sm.socket, "gethostbyaddr", return_value=("mx.example.net", [], [])),
        patch.object(sm.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("192.0.2.25", 0))]),
    ):
        assert real("192.0.2.25") == ("mx.example.net", True)
        assert real("192.0.2.99") == ("mx.example.net", False)
    with patch.object(sm.socket, "gethostbyaddr", side_effect=OSError):
        assert real("192.0.2.25") == (None, None)


def test_render(capsys):
    from xping.render.views import smtp as view

    port, _ = _server()
    with patch("xping.render.COLOR", False), patch("xping.render.ansi.COLOR", False):
        sm.smtp("127.0.0.1", port=port, timeout=3)
    out = capsys.readouterr().out
    assert "220 mail.test ESMTP ready" in out and "NOT offered" in out and "offers no encryption" in out
    assert "Reverse DNS       mail.test  ✔ resolves back" in out
    assert callable(view.print_result)


def test_parser_and_check_type(tmp_path):
    from xping.diagnostics.check import load_config

    args = build_parser().parse_args(["smtp", "example.net", "--port", "587", "--require-tls", "--no-mx"])
    assert (args.port, args.require_tls, args.no_mx) == (587, True, True)
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"checks": [{"type": "smtp", "host": "example.net", "require_tls": True}]}))
    assert load_config(str(path))[0]["name"] == "smtp example.net"
