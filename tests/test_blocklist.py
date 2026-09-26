"""xping blocklist — DNSBL / RHSBL lookups (resolver faked)."""

import json
from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.cli.verdict import evaluate
from xping.diagnostics import blocklist as bl
from xping.exporters.csv import export_csv
from xping.exporters.json import export_json


def test_reverse_ip():
    assert bl.reverse_ip("192.0.2.10") == "10.2.0.192"


@pytest.mark.parametrize(
    ("zone", "codes", "status"),
    [
        ("bl.spamcop.net", [], "clean"),
        ("bl.spamcop.net", ["127.0.0.2"], "listed"),
        ("zen.spamhaus.org", ["127.0.0.10"], "policy"),  # PBL only
        ("zen.spamhaus.org", ["127.0.0.4", "127.0.0.10"], "listed"),  # XBL wins
        ("zen.spamhaus.org", ["127.255.255.254"], "refused"),  # public resolver
        ("dbl.spamhaus.org", ["127.0.1.255"], "refused"),
        ("multi.uribl.com", ["127.0.0.1"], "refused"),
        ("multi.surbl.org", ["127.0.0.1"], "refused"),
        ("dnsbl.dronebl.org", ["127.0.0.1"], "listed"),  # 127.0.0.1 is a real code here
        ("bl.spamcop.net", ["93.184.216.34"], "error"),  # hijacked NXDOMAIN
    ],
)
def test_classify(zone, codes, status):
    assert bl.classify(zone, codes)[0] == status


def test_zen_reasons():
    status, reason = bl.classify("zen.spamhaus.org", ["127.0.0.2", "127.0.0.11"])
    assert status == "listed" and reason == "SBL (spam source)"


def _fake_lookup(listed: dict):
    def lookup(name, timeout):
        return listed.get(name, []), 12.0

    return lookup


def test_ip_check_queries_every_list():
    queried = []

    def lookup(name, timeout):
        queried.append(name)
        return (["127.0.0.2"] if name == "10.2.0.192.bl.spamcop.net" else []), 5.0

    with patch.object(bl, "lookup_a", side_effect=lookup):
        result = bl.blocklist("192.0.2.10", quiet=True)
    assert len(queried) == len(bl.IP_LISTS) and result.kind == "ip"
    assert result.listed == ["SpamCop (192.0.2.10)"] and result.answered == len(bl.IP_LISTS)
    assert "listed on: SpamCop" in evaluate(result)[0].message


def test_domain_checks_domain_lists_and_mail_ips():
    fake = _fake_lookup({"example.net.dbl.spamhaus.org": ["127.0.1.2"]})
    with (
        patch.object(bl, "lookup_a", side_effect=fake),
        patch.object(bl, "mail_and_web_addresses", return_value=["192.0.2.25", "2001:db8::25"]),
    ):
        result = bl.blocklist("Example.NET.", quiet=True)
    assert result.target == "example.net" and result.kind == "domain"
    assert result.addresses == ["192.0.2.25"] and result.skipped == ["2001:db8::25"]
    assert len(result.checks) == len(bl.DOMAIN_LISTS) + len(bl.IP_LISTS)
    assert result.listed == ["Spamhaus DBL (example.net)"]


def test_extra_zone_and_errors():
    def lookup(name, timeout):
        return (None, 5000.0) if name.endswith("bl.example.org") else ([], 3.0)

    with patch.object(bl, "lookup_a", side_effect=lookup):
        result = bl.blocklist("192.0.2.10", extra_zones=["bl.example.org"], quiet=True)
    extra = result.checks[-1]
    assert extra.zone == "bl.example.org" and extra.status == "error"
    assert evaluate(result) == []  # an unreachable list is not a listing


def test_nothing_answers_and_unresolvable_domain():
    with patch.object(bl, "lookup_a", return_value=(None, 1.0)):
        assert "no blocklist answered" in bl.blocklist("192.0.2.10", quiet=True).error
    with (
        patch.object(bl, "lookup_a", return_value=([], 1.0)),
        patch.object(bl, "mail_and_web_addresses", return_value=[]),
    ):
        result = bl.blocklist("nothing.invalid", quiet=True)
    assert "cannot resolve" in result.error and evaluate(result)


def test_lookup_a_distinguishes_nxdomain_from_failure():
    import socket

    nx = socket.gaierror(getattr(socket, "EAI_NONAME", -2), "not found")
    with patch.object(bl.socket, "gethostbyname_ex", side_effect=nx):
        assert bl.lookup_a("x", 1)[0] == []
    fail = socket.gaierror(getattr(socket, "EAI_AGAIN", -3), "temporary failure")
    with patch.object(bl.socket, "gethostbyname_ex", side_effect=fail):
        assert bl.lookup_a("x", 1)[0] is None
    with patch.object(bl.socket, "gethostbyname_ex", return_value=("x", [], ["127.0.0.3", "127.0.0.2"])):
        assert bl.lookup_a("x", 1)[0] == ["127.0.0.2", "127.0.0.3"]


def test_render_and_exports(capsys):
    fake = _fake_lookup({"10.2.0.192.zen.spamhaus.org": ["127.0.0.10"]})
    with patch.object(bl, "lookup_a", side_effect=fake), patch("xping.render.COLOR", False):
        result = bl.blocklist("192.0.2.10")
    out = capsys.readouterr().out
    assert "ℹ policy" in out and "PBL lists end-user address ranges" in out
    assert "Not listed on any" in out and evaluate(result) == []
    data = json.loads(export_json(result))
    assert data["listed_count"] == 0 and data["checks"][0]["status"] == "policy"
    assert export_csv(result).splitlines()[0] == "list,zone,subject,status,codes,reason"


def test_parser_and_check_type(tmp_path):
    from xping.diagnostics.check import load_config

    args = build_parser().parse_args(["blocklist", "mail.example.net", "--zone", "a.test", "--zone", "b.test"])
    assert args.zone == ["a.test", "b.test"] and args.timeout == 5.0
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"checks": [{"type": "blocklist", "target": "192.0.2.25"}]}))
    assert load_config(str(path))[0]["name"] == "blocklist 192.0.2.25"
