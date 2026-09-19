"""Tests for diagnostic result serialization."""

import json

import pytest


def test_ping_result_to_dict_includes_computed_fields():
    from xping.ping import PingResult
    result = PingResult(host="test", ip="1.1.1.1", count=3, rtts=[10.0, 20.0, -1.0])
    data = result.to_dict()
    assert data["host"] == "test"
    assert data["loss_pct"] == pytest.approx(33.333, rel=0.01)
    assert data["avg_rtt"] == 15.0
    json.dumps(data)


def test_hop_to_dict():
    from xping.trace import Hop
    hop = Hop(ttl=2, host="router", ip="10.0.0.1", rtts=[5.0, 6.0])
    data = hop.to_dict()
    assert data["label"] == "router (10.0.0.1)"
    assert data["avg_rtt"] == 5.5


def test_tcp_result_to_dict_nested_attempts():
    from xping.tcp import TcpAttempt, TcpResult
    result = TcpResult(
        host="example.com",
        port=443,
        ip="93.184.216.34",
        attempts=[TcpAttempt(seq=1, ok=True, elapsed_ms=4.0)],
    )
    data = result.to_dict()
    assert data["successful"] == 1
    assert data["attempts"][0]["elapsed_ms"] == 4.0


def test_portscan_result_open_ports_are_dicts():
    from xping.portscan import PortResult, PortScanResult
    result = PortScanResult(
        host="host",
        ip="1.1.1.1",
        ports=[443],
        results=[PortResult(port=443, open=True, elapsed_ms=2.0, service="https")],
    )
    data = result.to_dict()
    assert data["open_ports"][0]["service"] == "https"
    assert data["closed_ports"] == 0


def test_sweep_result_to_dict():
    from xping.sweep import HostProbe, SweepResult
    result = SweepResult(
        target="192.0.2.0/30",
        ports=[80],
        hosts=[HostProbe(ip="192.0.2.1", open_ports=[80], elapsed_ms=3.0)],
    )
    data = result.to_dict()
    assert data["alive_count"] == 1
    assert data["alive_hosts"][0]["alive"] is True


def test_ipscan_result_to_dict():
    from xping.ipscan import IpProbe, IpScanResult
    result = IpScanResult(
        target="192.0.2.0/30",
        probes=[IpProbe(ip="192.0.2.1", alive=True, elapsed_ms=1.0, rtt_ms=0.5)],
    )
    data = result.to_dict()
    assert data["alive_count"] == 1


def test_dns_result_to_dict():
    from xping.lookup import DnsResult
    result = DnsResult(host="example.com", ipv4=["93.184.216.34"], mx=[(10, "mail.example.com")])
    data = result.to_dict()
    assert data["ipv4"] == ["93.184.216.34"]
    assert data["mx"] == [[10, "mail.example.com"]]


def test_to_dict_rejects_non_dataclass():
    from xping.serialize import to_dict
    with pytest.raises(TypeError):
        to_dict({"not": "a dataclass"})


def test_to_dict_without_computed_fields():
    from xping.ping import PingResult
    result = PingResult(host="t", ip="1.1.1.1", count=1, rtts=[1.0])
    data = result.to_dict(include_computed=False)
    assert "loss_pct" not in data
    assert data["rtts"] == [1.0]
