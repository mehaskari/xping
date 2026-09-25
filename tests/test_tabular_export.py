"""CSV/Markdown export: one row per item instead of repr() blobs."""

import csv
import io

from xping.exporters import export_csv, export_markdown
from xping.models.dnscheck import DnsCheckItem, DnsCheckResult
from xping.models.health import HealthResult
from xping.models.http import HttpResult, RedirectHop
from xping.models.lookup import DnsResult
from xping.models.mtr import MtrHop, MtrResult
from xping.models.portscan import PortResult, PortScanResult
from xping.models.sweep import HostProbe, SweepResult
from xping.models.tls import TlsResult
from xping.models.trace import Hop


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


def test_trace_csv_has_one_row_per_hop_and_probe_columns():
    hops = [
        Hop(ttl=1, host="gw", ip="10.0.0.1", rtts=[1.0, 2.0, 3.0]),
        Hop(ttl=2, host=None, ip=None, rtts=[-1.0, -1.0, -1.0], timeout=True),
    ]
    rows = _rows(export_csv(hops))
    assert rows[0][:3] == ["ttl", "ip", "host"] and rows[0][-3:] == [
        "probe_1_ms",
        "probe_2_ms",
        "probe_3_ms",
    ]
    assert rows[1][:3] == ["1", "10.0.0.1", "gw"] and rows[1][-3:] == ["1", "2", "3"]
    assert rows[2][rows[0].index("timeout")] == "True" and rows[2][-1] == ""
    assert "[" not in export_csv(hops)  # no repr() of lists anywhere


def test_portscan_and_sweep_rows():
    scan = PortScanResult(
        host="h",
        ip="1.2.3.4",
        ports=[22, 80],
        results=[PortResult(22, True, 1.5, "ssh", "SSH-2.0-OpenSSH"), PortResult(80, False, 2.0)],
    )
    rows = _rows(export_csv(scan))
    assert rows[1][:4] == ["22", "open", "ssh", "SSH-2.0-OpenSSH"]
    assert rows[2][:2] == ["80", "closed"]
    sweep = SweepResult(target="10.0.0.0/30", ports=[22], hosts=[HostProbe("10.0.0.1", [22, 443])])
    assert _rows(export_csv(sweep))[1][:3] == ["10.0.0.1", "True", "22 443"]


def test_mtr_and_dns_rows():
    mtr = MtrResult(host="h", dest_ip="9.9.9.9", hops=[MtrHop(ttl=1, ip="9.9.9.9", rtts=[10.0, -1.0])])
    rows = _rows(export_csv(mtr))
    assert rows[1][rows[0].index("loss_pct")] == "50"
    dns = DnsResult(host="h", ipv4=["1.2.3.4"], mx=[(10, "mx.h")], txt=["v=spf1 -all"])
    types = [r[0] for r in _rows(export_csv(dns))[1:]]
    assert types == ["A", "MX", "TXT"]


def test_field_value_types_export_summary():
    tls = TlsResult(host="h", port=443, protocol="TLSv1.3", san=["a.h", "b.h"])
    rows = _rows(export_csv(tls))
    assert rows[0] == ["field", "value"] and ["protocol", "TLSv1.3"] in rows
    http = HttpResult(url="u", status_code=200, redirects=[RedirectHop("http://u", 301)])
    assert ["status_code", "200"] in _rows(export_csv(http))


def test_markdown_has_summary_and_sections():
    http = HttpResult(
        url="http://h",
        final_url="https://h",
        status_code=200,
        headers={"Server": "x|y"},
        redirects=[RedirectHop("http://h", 301)],
    )
    text = export_markdown(http)
    assert "| status_code | 200 |" in text
    assert "## Requests" in text and "| 1 | http://h | 301 |" in text
    assert "## Headers" in text and "x\\|y" in text  # pipes escaped


def test_markdown_empty_section_and_dnscheck():
    r = DnsCheckResult(domain="d", score=80, checks=[DnsCheckItem("SPF", "ok", "strict")])
    text = export_markdown(r)
    assert "| SPF | ok | strict |" in text
    assert "## Issues\n\n_none_" in export_markdown(HealthResult(host="h"))
