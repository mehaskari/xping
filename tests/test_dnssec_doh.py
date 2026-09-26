"""DNSSEC in dnscheck, and DNS-over-HTTPS in lookup."""

import io
import struct
import urllib.error
from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.diagnostics import dnssec
from xping.diagnostics import lookup as lk

# Real responses captured from a resolver (id 0xab12), github.com A and MX
GITHUB_A = bytes.fromhex(
    "ab12818000010001000000000667697468756203636f6d0000010001c00c0001000100000c8800048c527904"
)
GITHUB_MX = bytes.fromhex(
    "ab12818000010001000000000667697468756203636f6d00000f0001c00c000f000100000c21002700000a67"
    "69746875622d636f6d046d61696c0a70726f74656374696f6e076f75746c6f6f6bc013"
)

# ── DNSSEC ────────────────────────────────────────────────────────────────────


def test_query_has_edns_do_bit_and_optional_cd():
    packet = dnssec.build_query("example.net", dnssec.TYPE_DS, ident=0x1234)
    ident, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", packet[:12])
    assert (ident, qd, ar) == (0x1234, 1, 1) and flags == 0x0100  # RD only
    assert packet.endswith(b"\x00\x00\x29\x10\x00\x00\x00\x80\x00\x00\x00")  # OPT, 4096, DO
    cd = dnssec.build_query("example.net", dnssec.TYPE_SOA, cd=True, ident=1)
    assert struct.unpack("!H", cd[2:4])[0] & 0x0010


def _response(ident=1, rcode=0, ad=False, answer_types=()):
    flags = 0x8180 | rcode | (0x0020 if ad else 0)
    header = struct.pack("!HHHHHH", ident, flags, 1, len(answer_types), 0, 0)
    question = b"\x07example\x03net\x00" + struct.pack("!HH", 6, 1)
    answers = b"".join(
        b"\xc0\x0c" + struct.pack("!HHIH", t, 1, 300, 4) + b"\x00\x00\x00\x00" for t in answer_types
    )
    return header + question + answers


def test_parse_response_counts_types_and_flags():
    parsed = dnssec.parse_response(_response(ad=True, answer_types=(6, 46)), ident=1)
    assert parsed == {"rcode": "NOERROR", "ad": True, "tc": False, "types": {6: 1, 46: 1}}
    with pytest.raises(ValueError, match="ID"):
        dnssec.parse_response(_response(ident=2), ident=1)
    assert dnssec.parse_response(_response(rcode=2))["rcode"] == "SERVFAIL"


def _ans(rcode="NOERROR", ad=False, types=None):
    return {"rcode": rcode, "ad": ad, "tc": False, "types": types or {}}


@pytest.mark.parametrize(
    ("ds", "soa", "soa_cd", "status", "text"),
    [
        (_ans(types={43: 1}), _ans(ad=True, types={6: 1, 46: 1}), None, "ok", "validated"),
        (_ans(), _ans(types={6: 1}), None, "info", "Not signed"),
        (_ans(), _ans(types={6: 1, 46: 1}), None, "warn", "no DS record"),
        (_ans(types={43: 1}), _ans(types={6: 1, 46: 1}), None, "warn", "not validated"),
        (_ans(types={43: 1}), _ans("SERVFAIL"), _ans(types={6: 1}), "fail", "bogus"),
    ],
)
def test_evaluate(ds, soa, soa_cd, status, text):
    item = dnssec.evaluate(ds, soa, soa_cd)
    assert item.status == status and text in item.detail


def test_dnssec_check_falls_back_to_second_resolver():
    calls = []

    def fake_ask(name, qtype, server, cd=False, timeout=3.0):
        calls.append(server)
        if server == "1.1.1.1":
            raise TimeoutError
        return _ans(types={43: 1}) if qtype == dnssec.TYPE_DS else _ans(ad=True, types={46: 1})

    with patch.object(dnssec, "ask", side_effect=fake_ask):
        item = dnssec.dnssec_check("example.net")
    assert item.status == "ok" and calls[0] == "1.1.1.1" and "8.8.8.8" in calls


def test_dnssec_check_unknown_when_nothing_answers():
    with patch.object(dnssec, "ask", side_effect=OSError("network unreachable")):
        item = dnssec.dnssec_check("example.net")
    assert item.status == "unknown" and "network unreachable" in item.detail


def test_dnscheck_includes_dnssec_and_scores_it():
    from xping.diagnostics import dnscheck as dc
    from xping.models.lookup import DnsResult

    dns = DnsResult(host="example.net", ipv4=["192.0.2.1"], ns=["a", "b"], mx=[(10, "m1"), (20, "m2")],
                    txt=["v=spf1 -all"])
    bogus = dc.DnsCheckItem("DNSSEC", "fail", "bogus")
    with (
        patch.object(dc, "lookup", return_value=dns),
        patch.object(dc, "query_txt", return_value=(["v=DMARC1; p=reject"], None)),
        patch.object(dc, "_find_dkim", return_value=("default", None)),
        patch.object(dc, "dnssec_check", return_value=bogus),
    ):
        result = dc.dnscheck("example.net", quiet=True)
    assert result.checks[-1].name == "DNSSEC" and result.score < 100


# ── DoH ───────────────────────────────────────────────────────────────────────


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_doh_request_format_and_parsing():
    sent = {}

    def fake_urlopen(request, context=None, timeout=None):
        sent.update(url=request.full_url, method=request.get_method(),
                    ctype=request.get_header("Content-type"), body=request.data)
        return _Resp(GITHUB_A)

    with patch.object(lk.urllib.request, "urlopen", side_effect=fake_urlopen):
        status, records = lk._doh_query("github.com", 1, lk.doh_url("cloudflare"))
    assert (status, records) == ("NOERROR", ["140.82.121.4"])
    assert sent["url"] == "https://cloudflare-dns.com/dns-query" and sent["method"] == "POST"
    assert sent["ctype"] == "application/dns-message" and sent["body"] == lk._build_dns_packet("github.com", 1)


def test_doh_errors():
    http = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
    timeout = urllib.error.URLError(TimeoutError("timed out"))
    for exc, status in ((http, "HTTP 403"), (timeout, "TIMEOUT"), (urllib.error.URLError("x"), "ERROR")):
        with patch.object(lk.urllib.request, "urlopen", side_effect=exc):
            assert lk._doh_query("a.test", 1, "https://doh.test/dns-query") == (status, [])
    nx = bytearray(GITHUB_A)
    nx[3] = (nx[3] & 0xF0) | 3  # NXDOMAIN
    with patch.object(lk.urllib.request, "urlopen", return_value=_Resp(bytes(nx))):
        assert lk._doh_query("a.test", 1, "https://doh.test/dns-query") == ("NXDOMAIN", [])


def test_lookup_over_doh_fills_the_result():
    answers = {1: GITHUB_A, 15: GITHUB_MX}

    def fake_doh(host, qtype, url, timeout=5.0):
        data = answers.get(qtype)
        return ("NOERROR", lk._parse_dns_response(data, qtype)) if data else ("NOERROR", [])

    with (
        patch.object(lk, "_doh_query", side_effect=fake_doh),
        patch.object(lk, "_dig_query") as dig,
        patch.object(lk.socket, "gethostbyaddr", side_effect=OSError),
    ):
        result = lk.lookup("github.com", quiet=True, doh="google")
    dig.assert_not_called()
    assert result.transport == "doh" and result.resolver == "https://dns.google/dns-query"
    assert result.ipv4 == ["140.82.121.4"]
    assert result.mx == [(0, "github-com.mail.protection.outlook.com")]


def test_parser_doh():
    parser = build_parser()
    assert parser.parse_args(["lookup", "h", "--doh", "quad9"]).doh == "quad9"
    assert parser.parse_args(["lookup", "h", "--doh", "https://doh.test/q"]).doh.startswith("https://")
    for bad in (["lookup", "h", "--doh", "nope"], ["lookup", "h", "--doh", "google", "--server", "1.1.1.1"]):
        with pytest.raises(SystemExit):
            parser.parse_args(bad)
