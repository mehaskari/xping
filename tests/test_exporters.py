"""Tests for JSON, CSV, and Markdown exporters."""

import json

from xping.exporters.csv import export_csv
from xping.exporters.json import export_json
from xping.exporters.markdown import export_markdown
from xping.models.bundle import BundleResult
from xping.models.lookup import DnsResult
from xping.models.ping import PingResult
from xping.models.trace import Hop


def test_export_json_ping():
    result = PingResult(host="t", ip="1.1.1.1", count=2, rtts=[10.0, 20.0])
    payload = json.loads(export_json(result))
    assert payload["host"] == "t"
    assert payload["avg_rtt"] == 15.0


def test_export_csv_ping():
    result = PingResult(host="t", ip="1.1.1.1", count=1, rtts=[5.0])
    text = export_csv(result)
    assert "field,value" in text
    assert "host,t" in text


def test_export_markdown_trace_hops():
    hops = [Hop(ttl=1, host="gw", ip="10.0.0.1", rtts=[1.0, 2.0])]
    text = export_markdown(hops, title="Trace")
    assert "# Trace" in text
    assert "ttl" in text


def test_export_json_bundle():
    bundle = BundleResult(
        host="example.com",
        lookup=DnsResult(host="example.com", ipv4=["93.184.216.34"]),
        ping=PingResult(host="example.com", ip="93.184.216.34", count=1, rtts=[1.0]),
        trace=[Hop(ttl=1, host="gw", ip="10.0.0.1", rtts=[2.0])],
        tcp=[],
    )
    payload = json.loads(export_json(bundle))
    assert payload["host"] == "example.com"
    assert payload["lookup"]["ipv4"] == ["93.184.216.34"]
