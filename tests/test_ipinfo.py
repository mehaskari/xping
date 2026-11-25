"""xping ip — address kind, reverse DNS, ASN and blocklists (network faked)."""

import json
import socket
from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.diagnostics import ipinfo as ip_diag
from xping.diagnostics.asn import AsnInfo
from xping.exporters.json import export_json
from xping.models.blocklist import BlocklistCheck, BlocklistResult
from xping.models.ipinfo import IpInfoResult
from xping.models.rdns import RdnsResult
from xping.verdict import evaluate


@pytest.mark.parametrize(
    "ip, kind",
    [
        ("8.8.8.8", "public"),
        ("2606:4700:4700::1111", "public"),
        ("192.168.1.10", "private"),
        ("10.0.0.1", "private"),
        ("fd00::1", "private"),
        ("100.72.1.2", "CGNAT"),
        ("127.0.0.1", "loopback"),
        ("::1", "loopback"),
        ("169.254.10.1", "link-local"),
        ("fe80::1%en0", "link-local"),
        ("224.0.0.251", "multicast"),
        ("192.0.2.5", "documentation"),
        ("2001:db8::5", "documentation"),
        ("0.0.0.0", "unspecified"),
        ("240.0.0.1", "reserved"),
    ],
)
def test_scope(ip, kind):
    assert ip_diag.scope(ip) == kind


def test_forward_confirmed():
    answer = [(socket.AF_INET, 0, 0, "", ("8.8.8.8", 0))]
    with patch.object(ip_diag.socket, "getaddrinfo", return_value=answer):
        assert ip_diag.forward_confirmed("dns.google", "8.8.8.8")
        assert not ip_diag.forward_confirmed("dns.google", "8.8.4.4")
    with patch.object(ip_diag.socket, "getaddrinfo", side_effect=socket.gaierror):
        assert not ip_diag.forward_confirmed("nowhere.invalid", "8.8.8.8")


def _blocklist(listed=(), policy=()):
    checks = [BlocklistCheck("Spamhaus ZEN", "zen", "x", "clean")]
    checks += [BlocklistCheck(name, "z", "x", "listed") for name in listed]
    checks += [BlocklistCheck(name, "z", "x", "policy") for name in policy]
    return BlocklistResult(target="x", kind="ip", checks=checks)


def _run(target, *, ptr="dns.google", back=True, asn=True, listed=(), policy=(), **kw):
    rdns = RdnsResult(ip="x", hostname=ptr + "." if ptr else None)
    info = AsnInfo(asn=15169, name="GOOGLE, US", prefix="8.8.8.0/24", country="US")
    with (
        patch.object(ip_diag, "resolve", side_effect=lambda h, f=None: "8.8.8.8"),
        patch.object(ip_diag.rdns_diag, "rdns", return_value=rdns) as rdns_call,
        patch.object(ip_diag, "forward_confirmed", return_value=back),
        patch.object(ip_diag.asn_diag, "lookup", return_value=info if asn else None) as asn_call,
        patch.object(
            ip_diag.blocklist_diag, "blocklist", return_value=_blocklist(listed, policy)
        ) as bl_call,
        patch.object(ip_diag.net_diag, "_cf_trace", return_value={"ip": "203.0.113.9"}),
    ):
        result = ip_diag.ipinfo(target, quiet=True, **kw)
    return result, rdns_call, asn_call, bl_call


def test_public_address_gets_every_row():
    r, *_ = _run("dns.google")
    assert (r.ip, r.version, r.scope) == ("8.8.8.8", 4, "public")
    assert r.ptr == "dns.google" and r.fcrdns is True  # trailing dot dropped
    assert (r.asn, r.as_name, r.prefix, r.country) == (15169, "GOOGLE, US", "8.8.8.0/24", "US")
    assert r.blocklist_listed == [] and r.blocklist_checked == 1
    assert evaluate(r) == []


def test_listed_address_fails_and_policy_is_reported():
    r, *_ = _run("8.8.8.8", listed=("SpamCop",), policy=("Spamhaus PBL",))
    assert r.blocklist_listed == ["SpamCop"] and r.blocklist_policy == ["Spamhaus PBL"]
    [failure] = evaluate(r)
    assert "listed on: SpamCop" in failure.message


def test_no_blocklist_skips_it():
    r, _, _, bl_call = _run("8.8.8.8", blocklist=False)
    bl_call.assert_not_called()
    assert r.blocklist_checked == 0


def test_private_address_skips_asn_and_blocklists():
    with patch.object(ip_diag.rdns_diag, "rdns", return_value=RdnsResult(ip="x")):
        with patch.object(ip_diag.asn_diag, "lookup") as asn_call:
            with patch.object(ip_diag.blocklist_diag, "blocklist") as bl_call:
                r = ip_diag.ipinfo("192.168.1.1", quiet=True)
    asn_call.assert_not_called()
    bl_call.assert_not_called()
    assert r.scope == "private" and r.ptr is None and evaluate(r) == []


def test_own_public_address():
    r, *_ = _run(None)
    assert r.query == "" and r.ip == "203.0.113.9"


def test_own_address_falls_back_to_ipv6():
    answers = iter([{}, {"ip": "2001:db8::9"}])
    with patch.object(ip_diag.net_diag, "_cf_trace", side_effect=lambda url: next(answers)):
        assert ip_diag._own_address(None) == "2001:db8::9"
    with patch.object(ip_diag.net_diag, "_cf_trace", return_value={}):
        assert ip_diag._own_address(socket.AF_INET) is None


def test_errors():
    with patch.object(ip_diag, "resolve", side_effect=socket.gaierror):
        r = ip_diag.ipinfo("nope.invalid", quiet=True)
    assert r.error == "cannot resolve 'nope.invalid'" and evaluate(r)
    with patch.object(ip_diag.net_diag, "_cf_trace", return_value={}):
        r = ip_diag.ipinfo(None, quiet=True)
    assert r.error and "public address" in r.error


def test_json_export():
    r, *_ = _run("8.8.8.8")
    data = json.loads(export_json(r))
    assert data["asn"] == 15169 and data["scope"] == "public" and data["fcrdns"] is True


def test_cli():
    args = build_parser().parse_args(["ip"])
    assert args.address is None and not args.no_blocklist
    args = build_parser().parse_args(["ip", "1.1.1.1", "--no-blocklist", "-6"])
    assert args.address == "1.1.1.1" and args.no_blocklist and args.ipv6


def test_cmd_ip_passes_options():
    from xping.cli.commands import cmd_ip

    with patch("xping.diagnostics.ipinfo.ipinfo", return_value=IpInfoResult(query="")) as run:
        cmd_ip(build_parser().parse_args(["ip", "-q", "--no-blocklist"]))
    assert run.call_args.kwargs["target"] is None and run.call_args.kwargs["blocklist"] is False
