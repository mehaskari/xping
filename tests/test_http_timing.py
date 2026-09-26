"""http: per-phase timing waterfall and the security-header audit."""

from unittest.mock import patch

from xping.diagnostics.http import audit_headers
from xping.exporters.csv import export_csv
from xping.exporters.markdown import export_markdown
from xping.models.http import HttpResult
from xping.render.views import http as http_view


def _status(items):
    return {i.name: i.status for i in items}


GOOD = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=()",
    "Server": "nginx",
}


def test_all_headers_present():
    items = audit_headers("https://a.test/", "https://a.test/", GOOD)
    assert all(i.status == "ok" for i in items) and len(items) == 7


def test_header_names_are_case_insensitive():
    lower = {k.lower(): v for k, v in GOOD.items()}
    assert all(i.status == "ok" for i in audit_headers("https://a", "https://a", lower))


def test_missing_and_weak_headers():
    headers = {
        "strict-transport-security": "max-age=300",
        "x-content-type-options": "sniff",
        "server": "Apache/2.4.41 (Ubuntu)",
        "x-powered-by": "PHP/8.1.2",
    }
    status = _status(audit_headers("https://a", "https://a", headers))
    assert status["Strict-Transport-Security"] == "warn"  # max-age too short
    assert status["X-Content-Type-Options"] == "missing"
    assert status["Content-Security-Policy"] == "missing"
    assert status["Server"] == "warn" and status["X-Powered-By"] == "warn"


def test_csp_frame_ancestors_covers_x_frame_options():
    headers = {"Content-Security-Policy": "frame-ancestors 'none'"}
    items = {i.name: i for i in audit_headers("https://a", "https://a", headers)}
    assert items["X-Frame-Options"].status == "ok"
    assert "frame-ancestors" in items["X-Frame-Options"].note


def test_plain_http_and_upgrade():
    plain = _status(audit_headers("http://a", "http://a", {}))
    assert plain["HTTPS"] == "warn" and "Strict-Transport-Security" not in plain
    upgraded = {i.name: i for i in audit_headers("http://a", "https://a/", {})}
    assert upgraded["HTTPS"].status == "ok" and "redirects" in upgraded["HTTPS"].note


def _result():
    r = HttpResult(url="https://a.test", final_url="https://a.test/", status_code=200,
                   reason="OK", dns_ms=10.0, tcp_ms=20.0, tls_ms=30.0, ttfb_ms=40.0,
                   transfer_ms=0.0, total_ms=100.0, tls_version="TLSv1.3",
                   tls_cipher="TLS_AES_256_GCM_SHA384")
    r.security = audit_headers(r.url, r.final_url, {"X-Frame-Options": "DENY"})
    return r


def test_waterfall_bars_follow_each_other():
    rows = http_view.timing_rows(_result())
    assert [label for label, _, _ in rows] == [
        "DNS lookup", "TCP connect", "TLS handshake", "Server response", "Download",
    ]
    bars = [bar for _, _, bar in rows]
    assert bars[0] == "███" and bars[1] == "   ██████"  # 10 ms → 3 cells, then offset
    assert bars[3].startswith(" " * 18) and len(bars[4]) <= 30  # never past the width


def test_waterfall_without_tls_or_with_redirects():
    r = _result()
    r.tls_ms, r.redirect_ms = None, 50.0
    labels = [label for label, _, _ in http_view.timing_rows(r)]
    assert labels[0] == "Redirects" and "TLS handshake" not in labels


def test_view_and_exports(capsys):
    r = _result()
    with patch("xping.render.COLOR", False):
        http_view.print_result(r)
    out = capsys.readouterr().out
    assert "TLS handshake" in out and "TLSv1.3  TLS_AES_256_GCM_SHA384" in out
    assert "Security headers  2/7" in out
    md = export_markdown(r)
    assert "Security headers" in md and "Content-Security-Policy" in md
    assert "tls_ms,30" in export_csv(r)
