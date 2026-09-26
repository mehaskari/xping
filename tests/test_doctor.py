"""xping doctor — step logic and diagnosis, with every network probe faked."""

import json
from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.cli.verdict import evaluate
from xping.diagnostics import doctor as doc
from xping.exporters.csv import export_csv
from xping.exporters.json import export_json
from xping.models.net import NetInterface, NetResult


def _info(**overrides) -> NetResult:
    info = NetResult(
        hostname="mac",
        local_ipv4="192.168.1.20",
        gateway_ipv4="192.168.1.1",
        gateway_interface="en0",
        dns_servers=["192.168.1.1"],
        interfaces=[NetInterface("en0", "up", 1500, None, ["192.168.1.20/24"])],
    )
    for key, value in overrides.items():
        setattr(info, key, value)
    return info


@pytest.fixture
def healthy(monkeypatch):
    """Every probe succeeds; tests override the one they break."""
    probes = {
        "network_info": _info,
        "ping_ip": lambda ip, count=3, timeout=1.5: [5.0] * count,
        "tcp_connect": lambda ip, port=443, timeout=3.0: 20.0,
        "system_resolve": lambda name, timeout=5.0: ("104.16.1.1", 12.0),
        "direct_dns": lambda name, server="1.1.1.1": True,
        "captive_probe": lambda timeout=3.0: ("open", "no login page"),
        "https_probe": lambda timeout=5.0: ("ok", "TLS 1.3", 1000.0),
    }
    for name, fn in probes.items():
        monkeypatch.setattr(doc, name, fn)
    return monkeypatch


def _run(**kw):
    return doc.doctor(quiet=True, clock=lambda: 1000.0, **kw)


def _status(result):
    return {s.key: s.status for s in result.steps}


def test_all_good(healthy):
    result = _run()
    assert result.ok and evaluate(result) == []
    assert _status(result) == {
        "interface": "ok", "gateway": "ok", "internet": "ok", "dns": "ok",
        "quality": "ok", "captive": "ok", "https": "ok", "ipv6": "info",
    }
    assert result.diagnosis.startswith("Everything looks good")


def test_no_network_skips_everything(healthy):
    healthy.setattr(doc, "network_info", lambda: _info(local_ipv4=None, interfaces=[]))
    result = _run(target="example.com")
    assert _status(result)["interface"] == "fail"
    assert all(s.status == "skip" for s in result.steps[1:])
    assert "not connected" in result.diagnosis and evaluate(result)


def test_dhcp_failure(healthy):
    healthy.setattr(doc, "network_info", lambda: _info(local_ipv4="169.254.3.4"))
    result = _run()
    assert "did not give this machine an address" in result.diagnosis


def test_router_ok_but_no_internet(healthy):
    healthy.setattr(doc, "tcp_connect", lambda ip, port=443, timeout=3.0: None)
    result = _run()
    status = _status(result)
    assert status["internet"] == "fail"
    assert status["quality"] == status["captive"] == status["https"] == "skip"
    assert "no internet behind it" in result.diagnosis


def test_router_silent_and_no_internet(healthy):
    healthy.setattr(doc, "tcp_connect", lambda ip, port=443, timeout=3.0: None)
    healthy.setattr(doc, "ping_ip", lambda ip, count=3, timeout=1.5: [-1.0] * count)
    assert "Neither the router nor the internet" in _run().diagnosis


def test_broken_dns_vs_blocked_dns(healthy):
    healthy.setattr(doc, "system_resolve", lambda name, timeout=5.0: (None, 5000.0))
    result = _run()
    assert _status(result)["dns"] == "fail" and "public DNS does" in result.step("dns").detail
    assert "DNS" in result.diagnosis and "1.1.1.1" in result.hint
    healthy.setattr(doc, "direct_dns", lambda name, server="1.1.1.1": False)
    assert "seems blocked" in _run().step("dns").hint


def test_captive_portal(healthy):
    healthy.setattr(doc, "captive_probe", lambda timeout=3.0: ("portal", "HTTP 302 redirect"))
    result = _run()
    assert "login page" in result.diagnosis and not result.ok


def test_https_interception_and_clock(healthy):
    healthy.setattr(doc, "https_probe", lambda timeout=5.0: ("cert", "self-signed", None))
    assert "intercepted" in _run().diagnosis
    healthy.setattr(doc, "https_probe", lambda timeout=5.0: ("ok", "TLS 1.3", 1000.0 - 7200))
    result = _run()
    assert result.ok and result.step("https").status == "warn"
    assert "2.0 h ahead" in result.step("https").detail and "warnings" in result.diagnosis


def test_target(healthy):
    result = _run(target="example.com", port=22)
    assert result.step("target").status == "ok" and result.port == 22
    healthy.setattr(
        doc, "tcp_connect", lambda ip, port=443, timeout=3.0: None if port == 22 else 20.0
    )
    result = _run(target="example.com", port=22)
    assert result.step("target").status == "fail"
    assert result.diagnosis == "Your internet is fine — the problem is with example.com."


def test_slow_and_lossy_link_is_a_warning(healthy):
    healthy.setattr(
        doc, "ping_ip", lambda ip, count=3, timeout=1.5: [400.0, -1.0, 380.0][:count] + [-1.0] * (count - 3)
    )
    result = _run()
    assert result.step("quality").status == "warn" and result.ok


def test_ipv6_reported_but_never_fails(healthy):
    healthy.setattr(doc, "network_info", lambda: _info(local_ipv6="2001:db8::5"))
    assert _run().step("ipv6").status == "ok"
    healthy.setattr(
        doc, "tcp_connect", lambda ip, port=443, timeout=3.0: None if ":" in ip else 20.0
    )
    result = _run()
    assert result.step("ipv6").status == "info" and result.ok


def test_exports(healthy):
    result = _run(target="example.com")
    data = json.loads(export_json(result))
    assert data["ok"] is True and data["steps"][0]["key"] == "interface"
    csv = export_csv(result).splitlines()
    assert csv[0] == "step,name,status,detail,hint,elapsed_ms" and len(csv) == 10


def test_rendered_output(healthy, capsys):
    healthy.setattr(doc, "system_resolve", lambda name, timeout=5.0: (None, 5000.0))
    with patch("xping.render.COLOR", False):
        doc.doctor(clock=lambda: 1000.0)
    out = capsys.readouterr().out
    assert "✘  DNS" in out and "The internet works, but name lookups (DNS) fail." in out


def test_parser():
    args = build_parser().parse_args(["doctor"])
    assert args.host is None and args.port == 443
    args = build_parser().parse_args(["doctor", "db.local", "--port", "5432", "--json"])
    assert args.host == "db.local" and args.port == 5432 and args.json
