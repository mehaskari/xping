"""
Regression tests for: HTTP/2 ALPN mismatch, DMARC/DKIM lookup location,
macOS/Linux/Windows `listen` parsing, raw-DNS qtype filtering, DNS query
failures vs. absent records, and speedtest/osdetect export flags.
"""

import struct
import time
from unittest.mock import MagicMock, patch

import pytest

from xping.models.lookup import DnsResult

# ── http: ALPN ────────────────────────────────────────────────────────────────


class TestHttpAlpn:
    def test_request_connection_offers_only_http11(self):
        from xping.diagnostics import http as http_diag

        ctx = MagicMock()
        tls_sock = ctx.wrap_socket.return_value
        tls_sock.version.return_value = "TLSv1.3"
        tls_sock.cipher.return_value = ("TLS_AES_128_GCM_SHA256", "TLSv1.3", 128)
        conn = MagicMock()
        resp = MagicMock(status=200, reason="OK", version=11)
        resp.getheaders.return_value = []
        resp.getheader.return_value = None
        resp.read.return_value = b""
        conn.getresponse.return_value = resp

        with (
            patch.object(http_diag, "_ssl_context", return_value=ctx),
            patch.object(http_diag.socket, "create_connection") as create,
            patch.object(http_diag.http.client, "HTTPConnection", return_value=conn),
            patch.object(http_diag.socket, "gethostbyname", return_value="1.2.3.4"),
        ):
            d = http_diag._one_request("https://example.com/", timeout=1.0)

        ctx.set_alpn_protocols.assert_called_once_with(["http/1.1"])
        ctx.wrap_socket.assert_called_once_with(
            create.return_value, server_hostname="example.com"
        )
        assert conn.sock is tls_sock  # request goes over our TLS socket
        assert d["status"] == 200
        assert d["http_version"] == "HTTP/1.1"
        assert d["tls_version"] == "TLSv1.3" and d["tls_cipher"] == "TLS_AES_128_GCM_SHA256"
        assert d["tls_ms"] is not None and d["tcp_ms"] is not None

    def test_http10_response_version(self):
        from xping.diagnostics import http as http_diag

        conn = MagicMock()
        resp = MagicMock(status=200, reason="OK", version=10)
        resp.getheaders.return_value = []
        resp.getheader.return_value = None
        resp.read.return_value = b"x"
        conn.getresponse.return_value = resp
        with (
            patch.object(http_diag.socket, "create_connection"),
            patch.object(http_diag.http.client, "HTTPConnection", return_value=conn),
            patch.object(http_diag.socket, "gethostbyname", return_value="1.2.3.4"),
        ):
            d = http_diag._one_request("http://example.com/", timeout=1.0)
        assert d["http_version"] == "HTTP/1.0"
        assert d["tls_ms"] is None and d["transfer_ms"] >= 0


# ── dnscheck: DMARC / DKIM / query failures ───────────────────────────────────


def _run_dnscheck(dns: DnsResult, txt_answers: dict):
    """Run dnscheck with lookup() and query_txt() mocked.

    *txt_answers* maps a queried name to (records, error)."""
    from xping.diagnostics import dnscheck as dc

    def fake_query_txt(name, server=None):
        return txt_answers.get(name, ([], None))

    with (
        patch.object(dc, "lookup", return_value=dns),
        patch.object(dc, "query_txt", side_effect=fake_query_txt),
    ):
        return dc.dnscheck("example.com", quiet=True)


def _check(result, name):
    return next(item for item in result.checks if item.name == name)


def _healthy_dns() -> DnsResult:
    return DnsResult(
        host="example.com",
        ipv4=["93.184.216.34"],
        ns=["a.ns", "b.ns"],
        mx=[(10, "mx1"), (20, "mx2")],
        txt=["v=spf1 -all"],
    )


class TestDnsCheck:
    def test_dmarc_read_from_dmarc_subdomain(self):
        result = _run_dnscheck(
            _healthy_dns(),
            {"_dmarc.example.com": (["v=DMARC1; p=reject; rua=mailto:x@example.com"], None)},
        )
        assert _check(result, "DMARC").status == "ok"

    def test_apex_dmarc_text_is_not_used(self):
        dns = _healthy_dns()
        dns.txt.append("v=DMARC1; p=reject")
        result = _run_dnscheck(dns, {})
        assert _check(result, "DMARC").status == "fail"

    def test_subdomain_policy_does_not_mask_main_policy(self):
        result = _run_dnscheck(
            _healthy_dns(), {"_dmarc.example.com": (["v=DMARC1; p=none; sp=reject"], None)}
        )
        dmarc = _check(result, "DMARC")
        assert dmarc.status == "warn"
        assert "none" in dmarc.detail

    def test_dkim_found_at_common_selector(self):
        result = _run_dnscheck(
            _healthy_dns(),
            {"google._domainkey.example.com": (["v=DKIM1; k=rsa; p=MIIBIjAN"], None)},
        )
        dkim = _check(result, "DKIM")
        assert dkim.status == "ok"
        assert "google._domainkey" in dkim.detail

    def test_dkim_not_found_is_informational(self):
        result = _run_dnscheck(_healthy_dns(), {})
        assert _check(result, "DKIM").status == "info"

    def test_servfail_is_unknown_not_fail(self):
        dns = _healthy_dns()
        dns.txt = []
        dns.query_errors = {"TXT": "SERVFAIL"}
        result = _run_dnscheck(dns, {"_dmarc.example.com": ([], "SERVFAIL")})
        assert _check(result, "SPF").status == "unknown"
        assert _check(result, "DMARC").status == "unknown"
        assert result.unknown_count == 2
        assert result.fail_count == 0

    def test_unknown_checks_excluded_from_score(self):
        dns = _healthy_dns()
        dns.txt = []
        dns.query_errors = {"TXT": "SERVFAIL"}
        result = _run_dnscheck(dns, {"_dmarc.example.com": ([], "TIMEOUT")})
        # remaining scored checks: A, NS, MX — all ok
        assert result.score == 100


# ── raw DNS parsing ───────────────────────────────────────────────────────────


def _name(labels: str) -> bytes:
    out = b""
    for label in labels.split("."):
        out += bytes([len(label)]) + label.encode()
    return out + b"\x00"


def _cname_then_a_response(rcode: int = 0) -> bytes:
    header = struct.pack("!HHHHHH", 0xAB12, 0x8180 | rcode, 1, 2, 0, 0)
    question = _name("www.example.com") + struct.pack("!HH", 1, 1)
    cname_target = _name("example.com")
    cname = b"\xc0\x0c" + struct.pack("!HHIH", 5, 1, 60, len(cname_target)) + cname_target
    a = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + bytes([93, 184, 216, 34])
    return header + question + cname + a


class TestRawDns:
    def test_a_query_skips_cname_answers(self):
        from xping.diagnostics.lookup import _parse_dns_response

        assert _parse_dns_response(_cname_then_a_response(), 1) == ["93.184.216.34"]

    def test_response_status(self):
        from xping.diagnostics.lookup import _response_status

        assert _response_status(_cname_then_a_response(0)) == "NOERROR"
        assert _response_status(_cname_then_a_response(2)) == "SERVFAIL"
        assert _response_status(_cname_then_a_response(3)) == "NXDOMAIN"


# ── lookup: failed queries vs absent records ──────────────────────────────────


class TestLookupStatus:
    def test_servfail_reported_as_query_failure(self):
        from xping.diagnostics.lookup import lookup

        with patch("xping.diagnostics.lookup._dig_query", return_value=("SERVFAIL", "")):
            result = lookup("example.com", quiet=True)
        assert result.error.startswith("DNS query failed")
        assert result.query_errors["A"] == "SERVFAIL"

    def test_nxdomain_reported_as_no_records(self):
        from xping.diagnostics.lookup import lookup

        with patch("xping.diagnostics.lookup._dig_query", return_value=("NXDOMAIN", "")):
            result = lookup("example.invalid", quiet=True)
        assert result.error == "No DNS records found"
        assert result.query_errors == {}

    def test_query_txt_distinguishes_failure(self):
        from xping.diagnostics.lookup import query_txt

        with patch("xping.diagnostics.lookup._dig_query", return_value=("SERVFAIL", "")):
            assert query_txt("_dmarc.example.com") == ([], "SERVFAIL")
        with patch("xping.diagnostics.lookup._dig_query", return_value=("NXDOMAIN", "")):
            assert query_txt("_dmarc.example.com") == ([], None)

    def test_dig_status_parsing(self):
        from xping.diagnostics.lookup import _dig_query

        out = (
            ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n"
            ";; ANSWER SECTION:\n"
            "example.com.\t60\tIN\tA\t93.184.216.34\n"
        )
        proc = MagicMock(stdout=out)
        with patch("xping.diagnostics.lookup.subprocess.run", return_value=proc):
            status, answer = _dig_query("example.com", "A")
        assert status == "NOERROR"
        assert answer == "example.com.\t60\tIN\tA\t93.184.216.34"

    def test_dig_timeout_status(self):
        from xping.diagnostics.lookup import _dig_query

        proc = MagicMock(stdout=";; connection timed out; no servers could be reached\n")
        with patch("xping.diagnostics.lookup.subprocess.run", return_value=proc):
            assert _dig_query("example.com", "A", "10.255.255.1") == ("TIMEOUT", "")


# ── listen parsing ────────────────────────────────────────────────────────────

MACOS_NETSTAT = """\
Active Internet connections (including servers)
Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)
tcp4       0      0  127.0.0.1.53535        *.*                    LISTEN
tcp46      0      0  *.62563                *.*                    LISTEN
tcp6       0      0  ::1.631                *.*                    LISTEN
tcp4       0      0  192.168.1.5.50000      17.57.144.1.443        ESTABLISHED
udp4       0      0  *.5353                 *.*
udp4       0      0  192.168.1.5.60000      8.8.8.8.53
"""

LINUX_NETSTAT = """\
Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name
tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      812/sshd
tcp6       0      0 :::80                   :::*                    LISTEN      901/nginx: master
udp        0      0 0.0.0.0:68              0.0.0.0:*                           655/dhclient
"""

WINDOWS_NETSTAT = """\
  Proto  Local Address          Foreign Address        State
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING
  TCP    [::]:445               [::]:0                 LISTENING
  TCP    10.0.0.2:50000         1.1.1.1:443            ESTABLISHED
  UDP    0.0.0.0:123            *:*
"""


class TestListenParsing:
    def test_macos(self):
        from xping.diagnostics.listen import _parse_netstat_unix

        entries = _parse_netstat_unix(MACOS_NETSTAT)
        got = {(e.proto, e.local_addr, e.local_port) for e in entries}
        assert got == {
            ("tcp", "127.0.0.1", 53535),
            ("tcp", "*", 62563),
            ("tcp", "::1", 631),
            ("udp", "*", 5353),
        }

    def test_linux(self):
        from xping.diagnostics.listen import _parse_netstat_unix

        entries = {(e.proto, e.local_port): e for e in _parse_netstat_unix(LINUX_NETSTAT)}
        assert entries[("tcp", 22)].local_addr == "0.0.0.0"
        assert entries[("tcp", 22)].pid == 812
        assert entries[("tcp", 22)].process == "sshd"
        assert entries[("tcp", 80)].local_addr == "::"
        assert entries[("udp", 68)].process == "dhclient"

    def test_windows(self):
        from xping.diagnostics.listen import _parse_netstat_windows

        got = {(e.proto, e.local_addr, e.local_port) for e in _parse_netstat_windows(WINDOWS_NETSTAT)}
        assert got == {("tcp", "0.0.0.0", 135), ("tcp", "::", 445), ("udp", "0.0.0.0", 123)}

    def test_non_linux_uses_netstat_an(self):
        from xping.diagnostics import listen as listen_mod

        calls = []

        def fake_run(*cmd):
            calls.append(cmd)
            return None if cmd[0] == "ss" else MACOS_NETSTAT

        with (
            patch.object(listen_mod, "_run", side_effect=fake_run),
            patch.object(listen_mod.sys, "platform", "darwin"),
        ):
            result = listen_mod.listen(quiet=True)
        assert ("netstat", "-an") in calls
        assert result.count == 4


# ── export flags ──────────────────────────────────────────────────────────────


class TestExportFlags:
    @pytest.mark.parametrize(
        "argv", [["speedtest", "--json"], ["osdetect", "example.com", "--csv"]]
    )
    def test_parser_accepts_export_flags(self, argv):
        from xping.cli.parser import build_parser

        args = build_parser().parse_args(argv)
        assert args.json or args.csv

    def test_osdetect_exports_model(self, capsys):
        import json

        from xping.cli.commands import cmd_osdetect
        from xping.cli.parser import build_parser

        args = build_parser().parse_args(["osdetect", "example.com", "--json"])
        proc = MagicMock(stdout="64 bytes from 1.2.3.4: icmp_seq=0 ttl=57 time=10 ms", stderr="")
        with (
            patch("xping.diagnostics.osdetect.socket.gethostbyname", return_value="1.2.3.4"),
            patch("xping.diagnostics.osdetect.subprocess.run", return_value=proc),
        ):
            cmd_osdetect(args)
        data = json.loads(capsys.readouterr().out)
        assert data["ttl"] == 57
        assert data["os_guess"].startswith("Linux")

    def test_speedtest_exports(self, capsys):
        import json

        from xping.cli.commands import cmd_speedtest
        from xping.cli.parser import build_parser
        from xping.models.speedtest import SpeedResult

        args = build_parser().parse_args(["speedtest", "--json"])
        with patch(
            "xping.cli.commands.speedtest", return_value=SpeedResult(download_mbps=50.0)
        ) as fake:
            cmd_speedtest(args)
        fake.assert_called_once_with(connections=4, duration=8.0, quiet=True)
        assert json.loads(capsys.readouterr().out)["grade"] == "Good"


# ── TLS context, export fields, osdetect, trace, tcp ─────────────────────────


class TestSecureContext:
    def test_requires_tls12_and_verifies(self):
        import ssl

        from xping.diagnostics.sslctx import secure_context

        ctx = secure_context()
        assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname

    def test_rdap_never_falls_back_to_unverified_tls(self):
        from xping.diagnostics import whois as whois_diag

        with (
            patch.object(whois_diag, "_rdap_url_for", return_value="https://rdap.example"),
            patch.object(whois_diag.urllib.request, "urlopen", side_effect=OSError("tls")),
            patch.object(whois_diag.time, "sleep"),
            patch("ssl._create_unverified_context") as unverified,
        ):
            assert whois_diag._rdap_query("example.com", "com") is None
        unverified.assert_not_called()


class TestExportedExtras:
    def test_http_timing_fields_exported(self):
        import json

        from xping.exporters import export_json
        from xping.models.http import HttpResult

        r = HttpResult(url="https://x", dns_ms=1.5, tcp_ms=2.5, http_version="HTTP/1.1")
        r.h2_supported = True
        data = json.loads(export_json(r))
        assert data["dns_ms"] == 1.5
        assert data["tcp_ms"] == 2.5
        assert data["http_version"] == "HTTP/1.1"
        assert data["h2_supported"] is True

    def test_health_history_and_tls_chain_exported(self):
        from xping.models.health import HealthResult
        from xping.models.tls import TlsResult

        h = HealthResult(host="h", history=[{"ts": 1, "score": 90, "grade": "Excellent"}])
        assert h.to_dict()["history"][0]["score"] == 90
        t = TlsResult(host="h", port=443, chain=["leaf", "Root CA"])
        assert t.to_dict()["chain"] == ["leaf", "Root CA"]


class TestOsGuess:
    @pytest.mark.parametrize(
        ("ttl", "expected"),
        [
            (30, "Windows 95/NT (legacy)"),
            (57, "Linux / macOS / FreeBSD"),
            (64, "Linux / macOS / FreeBSD"),
            (117, "Windows"),
            (240, "Linux / Unix / Network device"),
            (300, "Unknown"),
        ],
    )
    def test_guess(self, ttl, expected):
        from xping.diagnostics.osdetect import _guess_os

        assert _guess_os(ttl)[0] == expected

    def test_extract_windows_ttl(self):
        from xping.diagnostics.osdetect import _extract_ttl

        assert _extract_ttl("Reply from 1.2.3.4: bytes=32 time=9ms TTL=117") == 117
        assert _extract_ttl("Request timed out.") is None


class TestTraceIpHeader:
    def test_icmp_type_read_after_ip_options(self):
        """An IPv4 header with options (IHL > 5) must not be misread as ICMP."""
        from xping.diagnostics import trace as trace_diag

        # IHL=6 → 24-byte header whose 4 option bytes start with 0x08, which a
        # fixed data[20] read would misparse as an ICMP echo *request*.
        ip_header = bytes([0x46]) + bytes(19) + bytes([8, 0, 0, 0])
        packet = ip_header + bytes([11, 0]) + bytes(6)  # ICMP time exceeded
        recv_sock, send_sock = MagicMock(), MagicMock()
        recv_sock.recvfrom.return_value = (packet, ("10.0.0.1", 0))
        with (
            patch.object(trace_diag.socket, "socket", side_effect=[recv_sock, send_sock]),
            patch.object(trace_diag.select, "select", return_value=([recv_sock], [], [])),
            patch.object(trace_diag, "_reverse", return_value=None),
        ):
            hop = trace_diag._raw_trace_hop("1.1.1.1", 1, 33435, probes=1)
        assert hop.ip == "10.0.0.1"
        assert not hop.timeout


class TestTcpUsesResolvedIp:
    def test_connects_to_resolved_address(self):
        from xping.diagnostics import tcp as tcp_diag
        from xping.models.tcp import TcpAttempt

        with (
            patch.object(tcp_diag, "_resolve", return_value="93.184.216.34"),
            patch.object(
                tcp_diag, "_connect_once", return_value=TcpAttempt(seq=1, ok=True, elapsed_ms=1.0)
            ) as connect,
        ):
            tcp_diag.tcp("example.com", 443, count=1, quiet=True)
        assert connect.call_args.args[0] == "93.184.216.34"


class TestUnreadableProfileStore:
    def test_permission_error_means_no_profiles(self):
        from xping.diagnostics import profile as profile_diag

        with patch.object(profile_diag.Path, "exists", side_effect=PermissionError(13, "denied")):
            assert profile_diag.resolve_target("example.com") == "example.com"
            assert profile_diag.list_profiles(quiet=True).count == 0


class TestRdapBootstrapTls:
    def test_bootstrap_uses_shared_tls_context(self):
        """The IANA bootstrap fetch must use certifi + TLS 1.2+ like every other HTTPS call."""
        from xping.diagnostics import whois as whois_diag

        sentinel = object()
        with (
            patch.object(whois_diag, "secure_context", return_value=sentinel),
            patch.object(whois_diag.urllib.request, "urlopen", side_effect=OSError("offline")) as urlopen,
        ):
            assert whois_diag._rdap_url_for("zz-not-hardcoded") is None
        assert urlopen.call_args.kwargs["context"] is sentinel


class TestSpinnerWidth:
    """A spinner line longer than the terminal wrapped, so each "\\r" redraw
    started a new line and the text piled up (seen with `doctor`)."""

    def test_fit_plain_and_colored(self):
        from xping.render.animations import _ANSI, fit

        assert fit("short", 10) == "short"
        assert fit("abcdefghij", 5) == "abcd…"
        colored = "\033[96mChecking connection quality\033[0m"
        cut = fit(colored, 10)
        assert _ANSI.sub("", cut) == "Checking …" and cut.endswith("\033[0m")
        assert fit("anything", 0) == ""

    def test_spinner_line_fits_terminal(self, monkeypatch):
        import io

        from xping.render import animations

        out = io.StringIO()
        monkeypatch.setattr(animations.sys, "stdout", out)
        monkeypatch.setattr(animations, "terminal_width", lambda: 40)
        spinner = animations.Spinner("Checking connection quality, login pages and HTTPS…")
        spinner.start()
        time.sleep(0.1)
        spinner.stop()
        frames = [f for f in out.getvalue().split("\r") if f.strip()]
        assert frames and all(len(animations._ANSI.sub("", f)) < 40 for f in frames)


class TestTableAlignment:
    """print_table measured coloured cells with len(), counting the colour
    codes, so the Value column and the borders drifted (trace summary)."""

    def test_columns_and_borders_line_up_with_and_without_colour(self, capsys):
        from xping.render import ansi, tables

        for colour in (False, True):
            with patch.object(ansi, "COLOR", colour), patch.object(tables, "COLOR", colour):
                rows = [
                    ["Total hops", "19"],
                    ["Responding hops", ansi.c("14", ansi.BRAND_MINT)],
                    ["Final hop RTT", ansi.c("117.96 ms", ansi.BOLD, ansi.BRAND_MINT)],
                ]
                tables.print_table(["Metric", "Value"], rows)
            lines = [ansi.ANSI_RE.sub("", ln) for ln in capsys.readouterr().out.splitlines()]
            assert len({len(ln) for ln in lines}) == 1, (colour, lines)  # same width
            # the column divider sits in the same place on every line
            divider = {next(i for i, ch in enumerate(ln) if ch in "┬│┼┴" and i > 3) for ln in lines}
            assert len(divider) == 1, (colour, lines)


def test_trace_rules_have_one_width(capsys):
    from xping.models.trace import Hop
    from xping.render.views import trace as trace_view

    with patch("xping.render.COLOR", False), patch("xping.render.ansi.COLOR", False):
        trace_view.hop_header()
        trace_view.print_summary([Hop(ttl=1, host=None, ip="1.1.1.1", rtts=[5.0])], "h", "1.1.1.1")
    rules = {len(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("───")}
    assert len(rules) == 1, rules
