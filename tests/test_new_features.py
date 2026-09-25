"""
Tests for features added in v1.2.0 / v1.2.5:
rdns, tls, http, whois, health, profile, mtr, mtu, ping --watch
"""

import json
import socket
from unittest.mock import MagicMock, patch

import pytest


# ── rdns ──────────────────────────────────────────────────────────────────────

class TestRdns:
    def test_ptr_name_ipv4(self):
        from xping.diagnostics.rdns import _ptr_name
        assert _ptr_name("8.8.8.8") == "8.8.8.8.in-addr.arpa"

    def test_ptr_name_ipv6(self):
        from xping.diagnostics.rdns import _ptr_name
        result = _ptr_name("2001:db8::1")
        assert result.endswith(".ip6.arpa")

    def test_is_ip_valid(self):
        from xping.diagnostics.rdns import _is_ip
        assert _is_ip("8.8.8.8") is True
        assert _is_ip("2001:db8::1") is True

    def test_is_ip_invalid(self):
        from xping.diagnostics.rdns import _is_ip
        assert _is_ip("not-an-ip") is False
        assert _is_ip("google.com") is False

    def test_rdns_invalid_ip(self):
        from xping.diagnostics.rdns import rdns
        result = rdns("not-an-ip", quiet=True)
        assert result.error is not None
        assert result.hostname is None

    def test_rdns_system_resolver_success(self):
        from xping.diagnostics.rdns import rdns
        with patch("xping.diagnostics.rdns.socket.gethostbyaddr",
                   return_value=("dns.google", [], ["8.8.8.8"])):
            result = rdns("8.8.8.8", quiet=True)
        assert result.hostname == "dns.google"
        assert result.error is None

    def test_rdns_fallback_on_herror(self):
        from xping.diagnostics.rdns import rdns
        with patch("xping.diagnostics.rdns.socket.gethostbyaddr",
                   side_effect=socket.herror):
            with patch("xping.diagnostics.rdns._fallback_ptr",
                       return_value="dns.google"):
                result = rdns("8.8.8.8", quiet=True)
        assert result.hostname == "dns.google"

    def test_rdns_no_ptr_record(self):
        from xping.diagnostics.rdns import rdns
        with patch("xping.diagnostics.rdns.socket.gethostbyaddr",
                   side_effect=socket.herror):
            with patch("xping.diagnostics.rdns._fallback_ptr", return_value=None):
                result = rdns("1.2.3.4", quiet=True)
        assert result.error is not None
        assert "No PTR record" in result.error

    def test_rdns_dns_query_bytes(self):
        from xping.diagnostics.rdns import _dns_query_bytes
        pkt = _dns_query_bytes("8.8.8.8.in-addr.arpa", qtype=12)
        assert len(pkt) > 12
        assert pkt[5] == 1  # 1 question

    def test_rdns_result_to_dict(self):
        from xping.models.rdns import RdnsResult
        r = RdnsResult(ip="8.8.8.8", hostname="dns.google")
        d = r.to_dict()
        assert d["hostname"] == "dns.google"
        assert d["resolved"] is True
        json.dumps(d)

    def test_rdns_result_unresolved(self):
        from xping.models.rdns import RdnsResult
        r = RdnsResult(ip="1.2.3.4")
        assert r.resolved is False


# ── tls ───────────────────────────────────────────────────────────────────────

class TestTls:
    def test_tls_unresolvable_host(self):
        from xping.diagnostics.tls import tls
        with patch("xping.diagnostics.tls.socket.gethostbyname",
                   side_effect=socket.gaierror):
            result = tls("bad.invalid", quiet=True)
        assert result.error is not None

    def test_tls_connection_refused(self):
        from xping.diagnostics.tls import tls
        with patch("xping.diagnostics.tls.socket.gethostbyname", return_value="1.2.3.4"):
            with patch("xping.diagnostics.tls.socket.create_connection",
                       side_effect=ConnectionRefusedError):
                result = tls("example.com", quiet=True)
        assert result.error is not None

    def test_tls_result_days_remaining(self):
        import time
        from xping.models.tls import TlsResult
        future = time.strftime("%b %d %H:%M:%S %Y GMT",
                               time.gmtime(time.time() + 86400 * 30))
        r = TlsResult(host="h", port=443, not_after=future)
        days = r.days_remaining
        assert days is not None
        assert 28 <= days <= 31

    def test_tls_result_expired(self):
        from xping.models.tls import TlsResult
        r = TlsResult(host="h", port=443, not_after="Jan  1 00:00:00 2020 GMT")
        assert r.expired is True

    def test_tls_result_expiring_soon(self):
        import time
        from xping.models.tls import TlsResult
        soon = time.strftime("%b %d %H:%M:%S %Y GMT",
                             time.gmtime(time.time() + 86400 * 7))
        r = TlsResult(host="h", port=443, not_after=soon)
        assert r.expiring_soon is True

    def test_tls_result_valid(self):
        from xping.models.tls import TlsResult
        r = TlsResult(host="h", port=443)
        assert r.valid is True
        r2 = TlsResult(host="h", port=443, error="failed")
        assert r2.valid is False

    def test_tls_result_to_dict(self):
        from xping.models.tls import TlsResult
        r = TlsResult(host="github.com", port=443, protocol="TLSv1.3",
                      not_after="Jan  1 00:00:00 2030 GMT")
        d = r.to_dict()
        assert d["protocol"] == "TLSv1.3"
        assert "days_remaining" in d
        json.dumps(d)

    def test_tls_mock_success(self):
        from xping.diagnostics.tls import tls

        fake_cert = {
            "subject": ((("commonName", "github.com"),),),
            "issuer": ((("organizationName", "DigiCert Inc"),),),
            "notBefore": "Jan  1 00:00:00 2024 GMT",
            "notAfter": "Jan  1 00:00:00 2030 GMT",
            "subjectAltName": (("DNS", "github.com"), ("DNS", "*.github.com")),
        }
        mock_tls_sock = MagicMock()
        mock_tls_sock.getpeercert.return_value = fake_cert
        mock_tls_sock.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
        mock_tls_sock.version.return_value = "TLSv1.3"
        mock_tls_sock.__enter__ = lambda s: s
        mock_tls_sock.__exit__ = MagicMock(return_value=False)

        mock_raw_sock = MagicMock()
        mock_raw_sock.__enter__ = lambda s: s
        mock_raw_sock.__exit__ = MagicMock(return_value=False)

        with patch("xping.diagnostics.tls.socket.gethostbyname", return_value="140.82.121.4"):
            with patch("xping.diagnostics.tls.socket.create_connection", return_value=mock_raw_sock):
                with patch("xping.diagnostics.tls.ssl.create_default_context") as mock_ctx:
                    mock_ctx.return_value.wrap_socket.return_value = mock_tls_sock
                    result = tls("github.com", quiet=True)

        assert result.protocol == "TLSv1.3"
        assert result.cipher == "TLS_AES_256_GCM_SHA384"
        assert result.error is None


# ── http ──────────────────────────────────────────────────────────────────────

class TestHttp:
    def test_http_unresolvable(self):
        from xping.diagnostics.http import http_diagnose
        with patch("xping.diagnostics.http.socket.gethostbyname",
                   side_effect=socket.gaierror):
            result = http_diagnose("http://bad.invalid", quiet=True)
        assert result.error is not None

    def test_http_missing_host(self):
        from xping.diagnostics.http import http_diagnose
        result = http_diagnose("not-a-url", quiet=True)
        # no host resolvable or error set
        assert result is not None

    def test_http_result_ok(self):
        from xping.models.http import HttpResult
        r = HttpResult(url="http://example.com", status_code=200, reason="OK")
        assert r.ok is True

    def test_http_result_not_ok(self):
        from xping.models.http import HttpResult
        r = HttpResult(url="http://example.com", status_code=404, reason="Not Found")
        assert r.ok is False

    def test_http_result_redirect_count(self):
        from xping.models.http import HttpResult, RedirectHop
        r = HttpResult(url="http://example.com",
                       redirects=[RedirectHop(url="http://example.com", status_code=301)])
        assert r.redirect_count == 1

    def test_http_result_to_dict(self):
        from xping.models.http import HttpResult
        r = HttpResult(url="https://example.com", status_code=200,
                       ttfb_ms=45.0, total_ms=120.0, body_bytes=1024)
        d = r.to_dict()
        assert d["status_code"] == 200
        assert d["ok"] is True
        assert d["redirect_count"] == 0
        json.dumps(d)

    def test_http_mock_200(self):
        from xping.diagnostics.http import http_diagnose

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.reason = "OK"
        mock_resp.read.return_value = b"<html></html>"
        mock_resp.getheaders.return_value = [("content-type", "text/html")]
        mock_resp.getheader.return_value = None

        with patch("xping.diagnostics.http.socket.gethostbyname", return_value="93.184.216.34"):
            with patch("xping.diagnostics.http.http.client.HTTPConnection") as mock_conn_cls:
                mock_conn = MagicMock()
                mock_conn.getresponse.return_value = mock_resp
                mock_conn_cls.return_value = mock_conn
                result = http_diagnose("http://example.com", quiet=True)

        assert result.status_code == 200
        assert result.error is None


# ── whois ─────────────────────────────────────────────────────────────────────

class TestWhois:
    def test_find_referral(self):
        from xping.diagnostics.whois import _find_referral
        text = "domain: COM\nrefer: whois.verisign-grs.com\n"
        assert _find_referral(text) == "whois.verisign-grs.com"

    def test_find_referral_whois_server(self):
        from xping.diagnostics.whois import _find_referral
        text = "WHOIS Server: whois.markmonitor.com\n"
        assert _find_referral(text) == "whois.markmonitor.com"

    def test_find_referral_none(self):
        from xping.diagnostics.whois import _find_referral
        assert _find_referral("no referral here") is None

    def test_parse_basic_fields(self):
        from xping.diagnostics.whois import _parse
        text = (
            "Domain Name: GITHUB.COM\n"
            "Registrar: MarkMonitor Inc.\n"
            "Creation Date: 2007-10-09T18:20:50Z\n"
            "Registry Expiry Date: 2025-10-09T18:20:50Z\n"
            "Updated Date: 2023-09-07T09:13:36Z\n"
            "Domain Status: clientDeleteProhibited\n"
            "Name Server: DNS1.P08.NSONE.NET\n"
        )
        fields = _parse(text)
        assert fields["registrar"] == "MarkMonitor Inc."
        assert fields["creation_date"] == "2007-10-09T18:20:50Z"
        assert "DNS1.P08.NSONE.NET".lower() in fields["name_servers"]
        assert "clientDeleteProhibited" in fields["status"]

    def test_parse_ignores_comments(self):
        from xping.diagnostics.whois import _parse
        text = "% This is a comment\n# Also a comment\nRegistrar: Test Inc.\n"
        fields = _parse(text)
        assert fields.get("registrar") == "Test Inc."

    def test_rdap_url_for_known_tlds(self):
        from xping.diagnostics.whois import _rdap_url_for
        assert "verisign" in _rdap_url_for("com")
        assert "verisign" in _rdap_url_for("net")
        assert _rdap_url_for("ir") is None  # .ir has no RDAP

    def test_whois_result_found(self):
        from xping.models.whois import WhoisResult
        r = WhoisResult(domain="github.com", registrar="MarkMonitor",
                        raw_text="Domain Name: GITHUB.COM")
        assert r.found is True

    def test_whois_result_not_found(self):
        from xping.models.whois import WhoisResult
        r = WhoisResult(domain="bad.invalid", error="not found")
        assert r.found is False

    def test_whois_result_to_dict(self):
        from xping.models.whois import WhoisResult
        r = WhoisResult(domain="cloudflare.com", registrar="MarkMonitor",
                        name_servers=["ns1.cloudflare.com"],
                        raw_text="Domain Name: CLOUDFLARE.COM")
        d = r.to_dict()
        assert d["registrar"] == "MarkMonitor"
        assert d["found"] is True
        json.dumps(d)

    def test_whois_port43_timeout_goes_to_rdap(self):
        from xping.diagnostics.whois import whois
        with patch("xping.diagnostics.whois._query",
                   side_effect=TimeoutError("timed out")):
            with patch("xping.diagnostics.whois._rdap_query") as mock_rdap:
                from xping.models.whois import WhoisResult
                mock_rdap.return_value = WhoisResult(
                    domain="github.com", registrar="MarkMonitor",
                    raw_text="{'handle': 'GITHUB-COM'}"
                )
                result = whois("github.com", quiet=True)
        assert result.registrar == "MarkMonitor"
        mock_rdap.assert_called_once()

    def test_whois_retry_on_os_error(self):
        from xping.diagnostics.whois import _query
        with patch("xping.diagnostics.whois.socket.getaddrinfo",
                   return_value=[(None, None, None, None, ("1.2.3.4", 43))]):
            with patch("xping.diagnostics.whois.socket.create_connection") as mock_conn:
                # simulate success on second try
                mock_sock = MagicMock()
                mock_sock.__enter__ = lambda s: s
                mock_sock.__exit__ = MagicMock(return_value=False)
                mock_sock.recv.side_effect = [b"Domain: GITHUB.COM\r\n", b""]
                mock_conn.side_effect = [OSError("refused"), mock_sock]
                with patch("xping.diagnostics.whois.time.sleep"):
                    text = _query("whois.verisign-grs.com", "github.com")
        assert mock_conn.call_count == 2
        assert "GITHUB.COM" in text


# ── health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_score_perfect(self):
        from xping.diagnostics.health import _score
        from xping.models.ping import PingResult
        r = PingResult(host="h", ip="1.1.1.1", count=8, rtts=[10.0] * 8)
        score, issues = _score(5.0, r)
        assert score >= 90
        assert issues == []

    def test_score_high_loss(self):
        from xping.diagnostics.health import _score
        from xping.models.ping import PingResult
        r = PingResult(host="h", ip="1.1.1.1", count=8, rtts=[-1.0] * 8)
        score, issues = _score(10.0, r)
        assert score == 0
        assert any("100%" in i for i in issues)

    def test_score_partial_loss(self):
        from xping.diagnostics.health import _score
        from xping.models.ping import PingResult
        r = PingResult(host="h", ip="1.1.1.1", count=8,
                       rtts=[-1.0] * 2 + [20.0] * 6)
        score, issues = _score(10.0, r)
        assert score < 100
        assert any("loss" in i.lower() for i in issues)

    def test_score_high_latency(self):
        from xping.diagnostics.health import _score
        from xping.models.ping import PingResult
        r = PingResult(host="h", ip="1.1.1.1", count=4, rtts=[400.0] * 4)
        score, issues = _score(10.0, r)
        assert score < 80
        assert any("latency" in i.lower() or "lag" in i.lower() for i in issues)

    def test_score_slow_dns(self):
        from xping.diagnostics.health import _score
        from xping.models.ping import PingResult
        r = PingResult(host="h", ip="1.1.1.1", count=4, rtts=[10.0] * 4)
        score, issues = _score(500.0, r)  # very slow DNS
        assert score < 100

    def test_health_result_grade(self):
        from xping.models.health import HealthResult
        cases = [(95, "Excellent"), (80, "Good"), (60, "Fair"), (30, "Poor"), (10, "Critical")]
        for s, expected_grade in cases:
            r = HealthResult(host="h", score=s)
            assert r.grade == expected_grade, f"score={s} expected {expected_grade} got {r.grade}"

    def test_health_result_to_dict(self):
        from xping.models.health import HealthResult
        from xping.models.ping import PingResult
        ping = PingResult(host="h", ip="1.1.1.1", count=4, rtts=[10.0] * 4)
        r = HealthResult(host="google.com", ip="8.8.8.8", score=92,
                         dns_resolve_ms=12.0, ping=ping)
        d = r.to_dict()
        assert d["score"] == 92
        assert d["grade"] == "Excellent"
        json.dumps(d)

    def test_health_dns_failure(self):
        from xping.diagnostics.health import health
        with patch("xping.diagnostics.health.socket.gethostbyname",
                   side_effect=socket.gaierror):
            result = health("bad.invalid", quiet=True)
        assert result.resolved is False
        assert result.score == 0
        assert result.issues


# ── profile ───────────────────────────────────────────────────────────────────

class TestProfile:
    @pytest.fixture(autouse=True)
    def tmp_profile_store(self, tmp_path):
        from xping.diagnostics import profile as pd
        self._orig_file = pd.STORE_FILE
        self._orig_dir = pd.STORE_DIR
        pd.STORE_FILE = tmp_path / "profiles.json"
        pd.STORE_DIR = tmp_path
        yield
        pd.STORE_FILE = self._orig_file
        pd.STORE_DIR = self._orig_dir

    def test_add_and_resolve(self):
        from xping.diagnostics.profile import add, resolve_target
        add("prod-db", "10.0.0.5", port=5432, quiet=True)
        assert resolve_target("prod-db") == "10.0.0.5"

    def test_resolve_unknown_returns_value(self):
        from xping.diagnostics.profile import resolve_target
        assert resolve_target("unknown-profile") == "unknown-profile"

    def test_list_profiles(self):
        from xping.diagnostics.profile import add, list_profiles
        add("a", "1.1.1.1", quiet=True)
        add("b", "2.2.2.2", quiet=True)
        result = list_profiles(quiet=True)
        assert result.count == 2
        names = [p.name for p in result.profiles]
        assert "a" in names and "b" in names

    def test_remove_profile(self):
        from xping.diagnostics.profile import add, list_profiles, remove
        add("temp", "3.3.3.3", quiet=True)
        removed = remove("temp", quiet=True)
        assert removed is True
        assert list_profiles(quiet=True).count == 0

    def test_remove_nonexistent(self):
        from xping.diagnostics.profile import remove
        removed = remove("no-such-profile", quiet=True)
        assert removed is False

    def test_add_invalid_name(self):
        from xping.diagnostics.profile import add
        result = add("bad name!", "1.1.1.1", quiet=True)
        assert result is None

    def test_profile_with_note(self):
        from xping.diagnostics.profile import add, get
        add("noted", "5.5.5.5", note="my server", quiet=True)
        entry = get("noted")
        assert entry.note == "my server"

    def test_profile_entry_to_dict(self):
        from xping.models.profile import ProfileEntry
        e = ProfileEntry(name="prod", target="10.0.0.1", port=22, note="main")
        d = e.to_dict()
        assert d["name"] == "prod"
        assert d["port"] == 22
        json.dumps(d)

    def test_profile_list_to_dict(self):
        from xping.models.profile import ProfileEntry, ProfileListResult
        r = ProfileListResult(profiles=[
            ProfileEntry(name="a", target="1.1.1.1"),
            ProfileEntry(name="b", target="2.2.2.2"),
        ])
        d = r.to_dict()
        assert d["count"] == 2
        json.dumps(d)


# ── mtr ───────────────────────────────────────────────────────────────────────

class TestMtr:
    def test_mtr_hop_stats(self):
        from xping.models.mtr import MtrHop
        hop = MtrHop(ttl=1, ip="10.0.0.1", host="gw", rtts=[1.0, 2.0, -1.0, 3.0])
        assert hop.sent == 4
        assert hop.received == 3
        assert abs(hop.loss_pct - 25.0) < 0.1
        assert hop.best == 1.0
        assert hop.worst == 3.0
        assert abs(hop.avg - 2.0) < 0.01

    def test_mtr_hop_all_timeout(self):
        from xping.models.mtr import MtrHop
        hop = MtrHop(ttl=3, rtts=[-1.0, -1.0, -1.0])
        assert hop.received == 0
        assert hop.loss_pct == 100.0
        assert hop.best == -1.0

    def test_mtr_hop_label_with_host(self):
        from xping.models.mtr import MtrHop
        hop = MtrHop(ttl=1, ip="10.0.0.1", host="router.local", rtts=[1.0])
        assert "router.local" in hop.label
        assert "10.0.0.1" in hop.label

    def test_mtr_hop_label_no_host(self):
        from xping.models.mtr import MtrHop
        hop = MtrHop(ttl=1, ip="10.0.0.1", rtts=[1.0])
        assert hop.label == "10.0.0.1"

    def test_mtr_hop_silent(self):
        from xping.models.mtr import MtrHop
        hop = MtrHop(ttl=2)
        assert hop.label == "???"

    def test_mtr_result_to_dict(self):
        from xping.models.mtr import MtrHop, MtrResult
        r = MtrResult(host="8.8.8.8", dest_ip="8.8.8.8", cycles=5,
                      hops=[MtrHop(ttl=1, ip="10.0.0.1", rtts=[1.0, 2.0])])
        d = r.to_dict()
        assert d["cycles"] == 5
        assert len(d["hops"]) == 1
        assert d["hops"][0]["loss_pct"] == 0.0
        json.dumps(d)

    def test_mtr_unresolvable_host(self):
        from xping.diagnostics.mtr import mtr
        with patch("xping.diagnostics.mtr.socket.gethostbyname",
                   side_effect=socket.gaierror):
            result = mtr("bad.invalid", quiet=True)
        assert result.error is not None

    def test_mtr_mock_run(self):
        from xping.diagnostics.mtr import mtr
        with patch("xping.diagnostics.mtr.socket.gethostbyname", return_value="8.8.8.8"):
            with patch("xping.diagnostics.mtr.discover_path",
                       return_value=[(1, "10.0.0.1"), (2, "8.8.8.8")]):
                with patch("xping.diagnostics.mtr.ping_once", return_value=5.0):
                    with patch("xping.diagnostics.mtr.time.sleep"):
                        result = mtr("8.8.8.8", cycles=2, quiet=True)
        assert len(result.hops) == 2
        assert result.cycles == 2


# ── mtu ───────────────────────────────────────────────────────────────────────

class TestMtu:
    def test_mtu_result_max_payload(self):
        from xping.models.mtu import ICMP_OVERHEAD_BYTES, MtuResult
        r = MtuResult(host="h", path_mtu=1500)
        assert r.max_payload == 1500 - ICMP_OVERHEAD_BYTES
        assert r.max_payload == 1472

    def test_mtu_result_none_payload(self):
        from xping.models.mtu import MtuResult
        r = MtuResult(host="h")
        assert r.max_payload is None

    def test_mtu_result_to_dict(self):
        from xping.models.mtu import MtuResult
        r = MtuResult(host="8.8.8.8", ip="8.8.8.8", path_mtu=1500,
                      probes=[{"size": 1472, "ok": True}])
        d = r.to_dict()
        assert d["path_mtu"] == 1500
        assert d["max_payload"] == 1472
        json.dumps(d)

    def test_mtu_unresolvable_host(self):
        from xping.diagnostics.mtu import mtu
        with patch("xping.diagnostics.mtu.socket.gethostbyname",
                   side_effect=socket.gaierror):
            result = mtu("bad.invalid", quiet=True)
        assert result.error is not None

    def test_mtu_probe_succeeded_true(self):
        from xping.diagnostics.platform_cmds import mtu_probe_succeeded
        assert mtu_probe_succeeded("64 bytes from 8.8.8.8: time=1.23 ms") is True

    def test_mtu_probe_succeeded_frag_needed(self):
        from xping.diagnostics.platform_cmds import mtu_probe_succeeded
        assert mtu_probe_succeeded("frag needed and DF set") is False

    def test_mtu_probe_succeeded_no_reply(self):
        from xping.diagnostics.platform_cmds import mtu_probe_succeeded
        assert mtu_probe_succeeded("Request timeout for icmp_seq 0") is False

    def test_mtu_probe_command_darwin(self):
        from xping.diagnostics.platform_cmds import mtu_probe_command
        with patch("xping.diagnostics.platform_cmds.system_name", return_value="darwin"):
            cmd = mtu_probe_command("8.8.8.8", 1000, 2.0)
        assert "-D" in cmd
        assert "-s" in cmd
        assert "1000" in cmd

    def test_mtu_probe_command_linux(self):
        from xping.diagnostics.platform_cmds import mtu_probe_command
        with patch("xping.diagnostics.platform_cmds.system_name", return_value="linux"):
            cmd = mtu_probe_command("8.8.8.8", 1000, 2.0)
        assert "do" in cmd
        assert "1000" in cmd

    def test_mtu_binary_search(self):
        from xping.diagnostics.mtu import mtu
        call_count = [0]
        def fake_probe(host, size, timeout):
            call_count[0] += 1
            return size <= 1400  # simulate path MTU of 1400

        with patch("xping.diagnostics.mtu.socket.gethostbyname", return_value="8.8.8.8"):
            with patch("xping.diagnostics.mtu.is_available", return_value=True):
                with patch("xping.diagnostics.mtu._probe", side_effect=fake_probe):
                    result = mtu("8.8.8.8", max_mtu=1500, quiet=True)
        assert result.path_mtu is not None
        assert result.path_mtu <= 1500
        assert call_count[0] > 0


# ── ping --watch ──────────────────────────────────────────────────────────────

class TestPingWatch:
    def test_redraw_watch_returns_line_count(self):
        from xping.render.views.ping import redraw_watch
        with patch("xping.render.COLOR", False):
            with patch("xping.render.views.ping.clear_lines"):
                count = redraw_watch([10.0, 20.0, -1.0, 15.0], printed_rows=0)
        assert isinstance(count, int)
        assert count > 0

    def test_redraw_watch_clears_previous(self):
        from xping.render.views.ping import redraw_watch
        with patch("xping.render.COLOR", False):
            with patch("xping.render.views.ping.clear_lines") as mock_clear:
                redraw_watch([10.0], printed_rows=5)
        mock_clear.assert_called_once_with(5)

    def test_watch_exits_on_keyboard_interrupt(self):
        from xping.diagnostics.ping import watch
        with patch("xping.diagnostics.ping.socket.gethostbyname", return_value="1.1.1.1"):
            with patch("xping.diagnostics.ping._icmp_ping", side_effect=[5.0, KeyboardInterrupt]):
                with patch("xping.render.COLOR", False):
                    with patch("xping.render.views.ping.redraw_watch", return_value=2):
                        with patch("xping.render.views.ping.print_summary"):
                            with patch("xping.diagnostics.ping.time.sleep"):
                                watch("1.1.1.1", interval=0)

    def test_watch_unresolvable(self):
        from xping.diagnostics.ping import watch
        with patch("xping.diagnostics.ping.socket.gethostbyname",
                   side_effect=socket.gaierror):
            with patch("builtins.print"):
                watch("bad.invalid")


# ── cli new commands ──────────────────────────────────────────────────────────

class TestCliNewCommands:
    def test_cmd_rdns(self):
        from xping.cli.commands import cmd_rdns
        from xping.cli.parser import build_parser
        from xping.models.rdns import RdnsResult
        args = build_parser().parse_args(["rdns", "8.8.8.8"])
        with patch("xping.cli.commands.rdns", return_value=RdnsResult(ip="8.8.8.8")):
            cmd_rdns(args)

    def test_cmd_tls(self):
        from xping.cli.commands import cmd_tls
        from xping.cli.parser import build_parser
        from xping.models.tls import TlsResult
        args = build_parser().parse_args(["tls", "github.com"])
        with patch("xping.cli.commands.tls", return_value=TlsResult(host="github.com", port=443)):
            cmd_tls(args)

    def test_cmd_http(self):
        from xping.cli.commands import cmd_http
        from xping.cli.parser import build_parser
        from xping.models.http import HttpResult
        args = build_parser().parse_args(["http", "https://example.com"])
        with patch("xping.cli.commands.http_diagnose",
                   return_value=HttpResult(url="https://example.com")):
            cmd_http(args)

    def test_cmd_whois(self):
        from xping.cli.commands import cmd_whois
        from xping.cli.parser import build_parser
        from xping.models.whois import WhoisResult
        args = build_parser().parse_args(["whois", "github.com"])
        with patch("xping.cli.commands.whois",
                   return_value=WhoisResult(domain="github.com")):
            cmd_whois(args)

    def test_cmd_health(self):
        from xping.cli.commands import cmd_health
        from xping.cli.parser import build_parser
        from xping.models.health import HealthResult
        from xping.models.ping import PingResult
        args = build_parser().parse_args(["health", "google.com"])
        ping = PingResult(host="google.com", ip="8.8.8.8", count=8, rtts=[10.0]*8)
        with patch("xping.cli.commands.health",
                   return_value=HealthResult(host="google.com", score=95, ping=ping)):
            cmd_health(args)

    def test_cmd_mtr(self):
        from xping.cli.commands import cmd_mtr
        from xping.cli.parser import build_parser
        from xping.models.mtr import MtrResult
        args = build_parser().parse_args(["mtr", "8.8.8.8", "--cycles", "3"])
        with patch("xping.cli.commands.mtr",
                   return_value=MtrResult(host="8.8.8.8")):
            cmd_mtr(args)

    def test_cmd_mtu(self):
        from xping.cli.commands import cmd_mtu
        from xping.cli.parser import build_parser
        from xping.models.mtu import MtuResult
        args = build_parser().parse_args(["mtu", "8.8.8.8"])
        with patch("xping.cli.commands.mtu",
                   return_value=MtuResult(host="8.8.8.8", path_mtu=1500)):
            cmd_mtu(args)

    def test_cmd_profile_add(self):
        from xping.cli.commands import cmd_profile
        from xping.cli.parser import build_parser
        args = build_parser().parse_args(["profile", "add", "myhost", "10.0.0.1"])
        with patch("xping.cli.commands.profile_diag.add") as mock_add:
            cmd_profile(args)
        mock_add.assert_called_once_with("myhost", "10.0.0.1", port=None, note=None)

    def test_cmd_profile_list(self):
        from xping.cli.commands import cmd_profile
        from xping.cli.parser import build_parser
        from xping.models.profile import ProfileListResult
        args = build_parser().parse_args(["profile", "list"])
        with patch("xping.cli.commands.profile_diag.list_profiles",
                   return_value=ProfileListResult()) as mock_list:
            cmd_profile(args)
        mock_list.assert_called_once()

    def test_cmd_profile_remove(self):
        from xping.cli.commands import cmd_profile
        from xping.cli.parser import build_parser
        args = build_parser().parse_args(["profile", "remove", "myhost"])
        with patch("xping.cli.commands.profile_diag.remove") as mock_rm:
            cmd_profile(args)
        mock_rm.assert_called_once_with("myhost")

    def test_cmd_ping_watch_flag(self):
        from xping.cli.commands import cmd_ping
        from xping.cli.parser import build_parser
        args = build_parser().parse_args(["ping", "google.com", "--watch"])
        with patch("xping.cli.commands.ping_watch") as mock_watch:
            cmd_ping(args)
        mock_watch.assert_called_once()

    def test_profile_resolution_in_ping(self):
        """profile name transparently resolves to stored target."""
        from xping.cli.commands import cmd_ping
        from xping.cli.parser import build_parser
        from xping.models.ping import PingResult
        args = build_parser().parse_args(["ping", "my-server", "-c", "1"])
        with patch("xping.cli.commands.profile_diag.resolve_target",
                   return_value="10.0.0.5") as mock_resolve:
            with patch("xping.cli.commands.ping",
                       return_value=PingResult(host="10.0.0.5", ip="10.0.0.5", count=1)):
                cmd_ping(args)
        mock_resolve.assert_called_once_with("my-server")


# ── export integration for new models ────────────────────────────────────────

class TestExportNewModels:
    def test_export_json_rdns(self):
        from xping.exporters.json import export_json
        from xping.models.rdns import RdnsResult
        r = RdnsResult(ip="8.8.8.8", hostname="dns.google")
        payload = json.loads(export_json(r))
        assert payload["hostname"] == "dns.google"
        assert payload["resolved"] is True

    def test_export_json_whois(self):
        from xping.exporters.json import export_json
        from xping.models.whois import WhoisResult
        r = WhoisResult(domain="github.com", registrar="MarkMonitor",
                        raw_text="raw")
        payload = json.loads(export_json(r))
        assert payload["registrar"] == "MarkMonitor"
        assert payload["found"] is True

    def test_export_json_health(self):
        from xping.exporters.json import export_json
        from xping.models.health import HealthResult
        from xping.models.ping import PingResult
        ping = PingResult(host="h", ip="1.1.1.1", count=4, rtts=[10.0]*4)
        r = HealthResult(host="google.com", score=95, ping=ping)
        payload = json.loads(export_json(r))
        assert payload["score"] == 95
        assert payload["grade"] == "Excellent"

    def test_export_json_mtr(self):
        from xping.exporters.json import export_json
        from xping.models.mtr import MtrHop, MtrResult
        r = MtrResult(host="8.8.8.8", cycles=5,
                      hops=[MtrHop(ttl=1, ip="10.0.0.1", rtts=[1.0, 2.0, 3.0])])
        payload = json.loads(export_json(r))
        assert payload["cycles"] == 5
        assert payload["hops"][0]["avg"] == 2.0

    def test_export_json_mtu(self):
        from xping.exporters.json import export_json
        from xping.models.mtu import MtuResult
        r = MtuResult(host="h", path_mtu=1500)
        payload = json.loads(export_json(r))
        assert payload["path_mtu"] == 1500
        assert payload["max_payload"] == 1472

    def test_export_csv_rdns(self):
        from xping.exporters.csv import export_csv
        from xping.models.rdns import RdnsResult
        r = RdnsResult(ip="8.8.8.8", hostname="dns.google")
        text = export_csv(r)
        assert "field,value" in text
        assert "dns.google" in text

    def test_export_markdown_health(self):
        from xping.exporters.markdown import export_markdown
        from xping.models.health import HealthResult
        r = HealthResult(host="google.com", score=92)
        text = export_markdown(r, title="Health Check")
        assert "Health Check" in text
        assert "92" in text
