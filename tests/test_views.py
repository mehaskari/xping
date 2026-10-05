"""Every terminal view renders realistic results, and the layout does not
depend on colour: with colour off there is not a single escape code, and
with colour on, stripping the codes gives exactly the same text. Padding
that counted colour codes (the cause of past column drift) breaks that.

Hostile text from the network (whois, DNS, certificates) carries an
escape sequence here; it must never reach the terminal.
"""

from __future__ import annotations

import time
from email.utils import formatdate
from unittest.mock import patch

import pytest

from xping.models.check import CheckOutcome, CheckReport
from xping.models.dnscheck import DnsCheckItem, DnsCheckResult
from xping.models.health import HealthResult
from xping.models.listen import ListenEntry, ListenResult
from xping.models.mtr import MtrHop
from xping.models.mtu import MtuResult
from xping.models.ping import PingResult
from xping.models.profile import ProfileEntry, ProfileListResult
from xping.models.propagation import PropagationResult, ResolverAnswer
from xping.models.rdns import RdnsResult
from xping.models.speedtest import SpeedResult
from xping.models.tls import TlsResult
from xping.models.whois import WhoisResult
from xping.render.ansi import ANSI_RE
from xping.render.views import check as check_view
from xping.render.views import dnscheck as dnscheck_view
from xping.render.views import health as health_view
from xping.render.views import listen as listen_view
from xping.render.views import mtr as mtr_view
from xping.render.views import mtu as mtu_view
from xping.render.views import profile as profile_view
from xping.render.views import propagation as propagation_view
from xping.render.views import rdns as rdns_view
from xping.render.views import speedtest as speedtest_view
from xping.render.views import tls as tls_view
from xping.render.views import whois as whois_view

EVIL = "evil\x1b]0;pwned\x07\x1b[2J"  # OSC title change + clear screen


def _cert_time(offset_days: float) -> str:
    """A date in the format ssl.getpeercert() uses."""
    stamp = formatdate(time.time() + offset_days * 86400, usegmt=True)  # 'Mon, 05 Oct 2026 …'
    day, month, year, clock = stamp.split()[1:5]
    return f"{month} {int(day):2d} {clock} {year} GMT"


def _ping(rtts):
    return PingResult(host="h", ip="192.0.2.1", count=len(rtts), rtts=rtts)


CASES = {
    "propagation": lambda: propagation_view.print_result(
        PropagationResult(
            name="example.com",
            rtype="A",
            expected=["192.0.2.10"],
            answers=[
                ResolverAnswer("Cloudflare", "1.1.1.1", "NOERROR", ["192.0.2.10"], 12.0),
                ResolverAnswer("Google", "8.8.8.8", "NOERROR", ["192.0.2.99", EVIL], 30.5),
                ResolverAnswer("Quad9", "9.9.9.9", "TIMEOUT", [], 2000.0),
                ResolverAnswer("System", None, "NXDOMAIN", [], 3.0),
            ],
        )
    ),
    "propagation-error": lambda: propagation_view.print_result(
        PropagationResult(name="x", rtype="A", error="no resolvers answered")
    ),
    "speedtest": lambda: speedtest_view.print_result(
        SpeedResult(
            download_mbps=245.3,
            upload_mbps=38.1,
            ping_ms=11.2,
            server="speed.cloudflare.com",
            connections=4,
            download_bytes=40_000_000,
            upload_bytes=8_000_000,
        )
    ),
    "speedtest-slow-no-upload": lambda: speedtest_view.print_result(
        SpeedResult(download_mbps=3.2, upload_mbps=None, ping_ms=120.0, connections=1)
    ),
    "speedtest-error": lambda: speedtest_view.print_result(SpeedResult(error="offline")),
    "tls": lambda: tls_view.print_result(
        TlsResult(
            host="example.com",
            port=443,
            ip="192.0.2.1",
            protocol="TLSv1.3",
            cipher="TLS_AES_256_GCM_SHA384",
            subject=f"CN=example.com {EVIL}",
            issuer="CN=R11, O=Let's Encrypt",
            not_before=_cert_time(-80),
            not_after=_cert_time(10),
            san=["example.com", "www.example.com", EVIL],
            chain=["CN=example.com", "CN=R11"],
        )
    ),
    "tls-expired": lambda: tls_view.print_result(
        TlsResult(
            host="old.test",
            port=8443,
            protocol="TLSv1.2",
            not_before=_cert_time(-400),
            not_after=_cert_time(-5),
        )
    ),
    "tls-error": lambda: tls_view.print_result(
        TlsResult(host="h", port=443, error="certificate verify failed")
    ),
    "health": lambda: health_view.print_summary(
        HealthResult(
            host="example.com",
            ip="192.0.2.1",
            dns_resolve_ms=14.0,
            ping=_ping([10.0, 12.5, -1.0, 11.0, 300.0, 9.0, 10.0, 10.5]),
            score=71,
            issues=["packet loss 12%", "high jitter"],
            history=[
                {"ts": time.time() - 3600 * i, "score": s, "grade": "Good"}
                for i, s in enumerate([60, 75, 80, 71])
            ],
        )
    ),
    "listen": lambda: listen_view.print_result(
        ListenResult(
            entries=[
                ListenEntry("tcp", "0.0.0.0", 22, 1, "sshd"),
                ListenEntry("tcp", "::", 443, 812, f"nginx {EVIL}"),
                ListenEntry("udp", "127.0.0.1", 53, None, None),
            ]
        )
    ),
    "listen-error": lambda: listen_view.print_result(ListenResult(error="permission denied")),
    "whois": lambda: whois_view.print_result(
        WhoisResult(
            domain="example.com",
            whois_server="whois.verisign-grs.com",
            registrar=f"Registrar {EVIL}",
            creation_date="1995-08-14",
            expiration_date="2027-08-13",
            updated_date="2026-08-14",
            status=["clientDeleteProhibited", EVIL],
            name_servers=["a.iana-servers.net", "b.iana-servers.net"],
        )
    ),
    "whois-error": lambda: whois_view.print_result(WhoisResult(domain="x", error="no server")),
    "dnscheck": lambda: dnscheck_view.print_result(
        DnsCheckResult(
            domain="example.com",
            ip="192.0.2.1",
            score=64,
            checks=[
                DnsCheckItem("SPF", "ok", "v=spf1 -all"),
                DnsCheckItem("DMARC", "warn", f"p=none {EVIL}"),
                DnsCheckItem("DKIM", "fail", "no selector found"),
                DnsCheckItem("MX", "info", "null MX"),
                DnsCheckItem("NS", "unknown", "query failed"),
            ],
        )
    ),
    "dnscheck-error": lambda: dnscheck_view.print_result(
        DnsCheckResult(domain="x", error="NXDOMAIN")
    ),
    "profile-list": lambda: profile_view.print_list(
        ProfileListResult(
            profiles=[
                ProfileEntry("prod-db", "10.0.0.5", 5432, "primary"),
                ProfileEntry("web", "example.com", None, None),
            ]
        )
    ),
    "profile-empty": lambda: profile_view.print_list(ProfileListResult()),
    "profile-saved": lambda: profile_view.print_saved(
        ProfileEntry("prod-db", "10.0.0.5", 5432, "primary")
    ),
    "profile-entry": lambda: profile_view.print_entry(ProfileEntry("web", "example.com")),
    "profile-removed": lambda: profile_view.print_removed("web"),
    "mtr": lambda: mtr_view.print_final(
        [
            MtrHop(1, "192.168.1.1", "router.lan", [1.0, 1.2, 0.9, 1.1]),
            MtrHop(2, None, None, [-1.0] * 4),
            MtrHop(3, "203.0.113.9", EVIL, [12.0, -1.0, 15.0, 13.0], 64500, "EXAMPLE-AS"),
            MtrHop(4, "192.0.2.1", "example.com", [20.0, 22.0, 21.0, 250.0]),
        ]
    ),
    "mtu": lambda: (
        mtu_view.print_probe(1472, True),
        mtu_view.print_probe(1473, False),
        mtu_view.print_summary(
            MtuResult(
                host="example.com",
                ip="192.0.2.1",
                path_mtu=1500,
                probes=[{"size": 1472, "ok": True}, {"size": 1473, "ok": False}],
            )
        ),
    ),
    "mtu-lowered": lambda: mtu_view.print_summary(
        MtuResult(host="vpn.test", ip="10.8.0.1", path_mtu=1420, method="socket")
    ),
    "rdns": lambda: rdns_view.print_result(
        RdnsResult("192.0.2.1", f"host.example {EVIL}", ["alias.example"], ["192.0.2.1"])
    ),
    "check": lambda: check_view.print_report(
        CheckReport(
            source="checks.toml",
            outcomes=[
                CheckOutcome("DNS", "ping", "1.1.1.1", True, "avg 9.0 ms, 0% loss", 210.0),
                CheckOutcome("DB", "tcp", "db:5432", False, f"refused {EVIL}", 2001.0),
            ],
        )
    ),
}


def _render(name: str, colour: bool, capsys) -> str:
    with patch("xping.render.ansi.COLOR", colour), patch("xping.render.COLOR", colour):
        CASES[name]()
    return capsys.readouterr().out


@pytest.mark.parametrize("name", sorted(CASES))
def test_view_layout_is_independent_of_colour(name, capsys):
    plain = _render(name, False, capsys)
    coloured = _render(name, True, capsys)
    assert plain.strip(), "the view printed nothing"
    assert "\x1b" not in plain and "\x07" not in plain
    assert ANSI_RE.sub("", coloured) == plain


@pytest.mark.parametrize("name", sorted(CASES))
def test_view_never_passes_remote_control_codes(name, capsys):
    coloured = _render(name, True, capsys)
    leftover = ANSI_RE.sub("", coloured)
    assert "\x1b" not in leftover and "\x07" not in leftover
    assert "\x1b]" not in coloured and "\x1b[2J" not in coloured


def test_mtr_redraw_reports_rows():
    hops = [MtrHop(1, "192.168.1.1", "router.lan", [1.0]), MtrHop(2, "192.0.2.1", None, [9.0])]
    with patch("xping.render.ansi.COLOR", False), patch("xping.render.COLOR", False):
        rows = mtr_view.redraw(hops, 1, 5)
        assert rows > len(hops)
        assert mtr_view.redraw(hops, 2, 5, rows) == rows  # same height on each redraw


def test_rdns_error_goes_to_stderr(capsys):
    rdns_view.print_error(RdnsResult("192.0.2.1", error="no PTR record"))
    captured = capsys.readouterr()
    assert captured.out == "" and "no PTR record" in captured.err


def test_check_describe_covers_every_result_type():
    from xping.models.blocklist import BlocklistResult
    from xping.models.lookup import DnsResult
    from xping.models.http import HttpResult
    from xping.models.ntp import NtpResult, NtpSample
    from xping.models.smtp import SmtpResult
    from xping.models.tcp import TcpAttempt, TcpResult
    from xping.models.udp import UdpAttempt, UdpResult

    samples = [
        _ping([5.0]),
        TcpResult(host="h", port=22, ip="192.0.2.1", attempts=[TcpAttempt(1, True, 3.0)]),
        HttpResult(url="https://h", status_code=200, total_ms=120.0),
        TlsResult(host="h", port=443, protocol="TLSv1.3", not_after=_cert_time(30)),
        DnsResult(host="h", ipv4=["192.0.2.1"]),
        DnsCheckResult(domain="h", score=90),
        HealthResult(host="h", score=95),
        BlocklistResult(target="192.0.2.1", kind="ip"),
        SmtpResult(host="h", server="mx.h", banner_code=220, tls_version="TLSv1.3"),
        UdpResult(host="h", port=53, attempts=[UdpAttempt(1, "open", 4.0)]),
        NtpResult(server="pool.ntp.org", stratum=2, samples=[NtpSample(1, 3.5, 20.0)]),
        PropagationResult(name="h", rtype="A", expected=["192.0.2.1"]),
        PropagationResult(name="h", rtype="A"),
    ]
    for result in samples:
        text = check_view.describe(result)
        assert text and text != "ok", type(result).__name__
