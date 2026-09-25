"""ASN lookups via Team Cymru DNS (trace/mtr --asn)."""

from unittest.mock import patch

import pytest

from xping.diagnostics import asn
from xping.models.mtr import MtrHop
from xping.models.trace import Hop
from xping.render.views._asn import short_name


@pytest.fixture(autouse=True)
def _clear_cache():
    asn._by_ip.clear()
    asn._names.clear()
    yield
    asn._by_ip.clear()
    asn._names.clear()


def test_origin_names():
    assert asn.origin_name("1.1.1.1") == "1.1.1.1.origin.asn.cymru.com"
    v6 = asn.origin_name("2606:4700:4700::1111")
    assert v6.endswith(".origin6.asn.cymru.com") and v6.startswith("1.1.1.1.0.0.0.0")
    assert v6.count(".") == 32 + 3
    for private in ("10.0.0.1", "192.168.1.1", "127.0.0.1", "fe80::1", "::1", "nonsense"):
        assert asn.origin_name(private) is None


def test_parse_origin_prefers_most_specific_prefix():
    records = [
        "49100 | 5.202.0.0/17 | IR | ripencc | 2012-08-29",
        "49100 | 5.202.112.0/24 | IR | ripencc | 2012-08-29",
    ]
    assert asn.parse_origin(records) == (49100, "5.202.112.0/24", "IR")
    assert asn.parse_origin(['"13335 209242 | 1.1.1.0/24 | AU | apnic | x"'])[0] == 13335
    assert asn.parse_origin(["garbage"]) is None and asn.parse_origin([]) is None
    assert asn.parse_origin(["", "  "]) is None


def test_parse_as_name_and_short_name():
    name = asn.parse_as_name(["13335 | US | arin | 2010-07-14 | CLOUDFLARENET - Cloudflare, Inc., US"])
    assert name == "CLOUDFLARENET - Cloudflare, Inc., US"
    assert short_name(name) == "CLOUDFLARENET"
    assert short_name("GOOGLE, US") == "GOOGLE"
    assert len(short_name("X" * 50, 10)) == 10 and short_name(None) == ""


def _fake_txt(name):
    if name == "1.1.1.1.origin.asn.cymru.com":
        return ["13335 | 1.1.1.0/24 | AU | apnic | 2011-08-11"], None
    if name == "AS13335.asn.cymru.com":
        return ["13335 | US | arin | 2010-07-14 | CLOUDFLARENET - Cloudflare, Inc., US"], None
    return [], None


def test_lookup_is_cached_and_skips_private():
    with patch.object(asn, "query_txt", side_effect=_fake_txt) as q:
        info = asn.lookup("1.1.1.1")
        assert info.asn == 13335 and info.name.startswith("CLOUDFLARENET") and info.country == "AU"
        assert asn.lookup("1.1.1.1") is info
        assert asn.lookup("192.168.1.1") is None and asn.lookup(None) is None
    assert q.call_count == 2  # one origin + one name query, then cache hits


def test_annotate_trace_and_mtr_hops():
    hops = [Hop(ttl=1, host=None, ip="192.168.1.1"), Hop(ttl=2, host=None, ip="1.1.1.1")]
    mtr_hops = [MtrHop(ttl=1, ip="1.1.1.1"), MtrHop(ttl=2, ip=None)]
    with patch.object(asn, "query_txt", side_effect=_fake_txt):
        for hop in hops:
            asn.annotate(hop)
        asn.annotate_all(mtr_hops)
    assert hops[0].asn is None and hops[1].asn == 13335
    assert mtr_hops[0].as_name.startswith("CLOUDFLARENET") and mtr_hops[1].asn is None


def test_trace_asn_flag_annotates_and_exports(capsys):
    from xping.diagnostics import trace as trace_diag
    from xping.exporters import export_csv

    hop = Hop(ttl=1, host="one.one.one.one", ip="1.1.1.1", rtts=[5.0])
    with (
        patch("socket.gethostbyname", return_value="1.1.1.1"),
        patch.object(trace_diag, "_native_hop", return_value=hop),
        patch.object(asn, "query_txt", side_effect=_fake_txt),
        patch("sys.stdout.isatty", return_value=False),
        patch("xping.render.COLOR", False),
    ):
        hops = trace_diag.trace("1.1.1.1", max_hops=3, asn=True)
    assert "AS13335 CLOUDFLARENET" in capsys.readouterr().out
    rows = export_csv(hops).splitlines()
    assert rows[1].split(",")[3] == "13335"
