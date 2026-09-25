"""IPv6 resolution, native ICMP (unprivileged ping sockets), IPv6 command variants."""

import socket
import struct
from unittest.mock import MagicMock, patch

import pytest

from xping.diagnostics import icmp
from xping.diagnostics.resolve import family_of, is_ipv6, resolve

# ── resolve ───────────────────────────────────────────────────────────────────


class TestResolve:
    def test_literals_pass_through(self):
        assert resolve("1.2.3.4") == "1.2.3.4"
        assert resolve("2001:db8::1") == "2001:db8::1"

    def test_literal_family_mismatch(self):
        with pytest.raises(socket.gaierror):
            resolve("1.2.3.4", socket.AF_INET6)
        with pytest.raises(socket.gaierror):
            resolve("2001:db8::1", socket.AF_INET)

    def test_prefers_ipv4(self):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            assert resolve("example.com") == "93.184.216.34"

    def test_falls_back_to_ipv6_only_hosts(self):
        v6 = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::7", 0, 0, 0))]
        with (
            patch("socket.gethostbyname", side_effect=socket.gaierror("no A")),
            patch("socket.getaddrinfo", return_value=v6),
        ):
            assert resolve("v6only.example") == "2001:db8::7"

    def test_forced_ipv4_does_not_fall_back(self):
        with patch("socket.gethostbyname", side_effect=socket.gaierror("no A")):
            with pytest.raises(socket.gaierror):
                resolve("v6only.example", socket.AF_INET)

    def test_forced_ipv6_skips_ipv4(self):
        v6 = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::9", 0, 0, 0))]
        with (
            patch("socket.gethostbyname") as v4,
            patch("socket.getaddrinfo", return_value=v6),
        ):
            assert resolve("dual.example", socket.AF_INET6) == "2001:db8::9"
        v4.assert_not_called()

    def test_family_of_and_is_ipv6(self):
        from types import SimpleNamespace

        assert family_of(SimpleNamespace(ipv4=False, ipv6=True)) == socket.AF_INET6
        assert family_of(SimpleNamespace(ipv4=True, ipv6=False)) == socket.AF_INET
        assert family_of(SimpleNamespace()) is None
        assert is_ipv6("fe80::1%en0") and not is_ipv6("10.0.0.1") and not is_ipv6("host")


# ── ICMP packets ──────────────────────────────────────────────────────────────


def _ipv4_header(ihl_words: int = 5) -> bytes:
    return bytes([0x40 | ihl_words]) + bytes(ihl_words * 4 - 1)


class TestIcmpPackets:
    def test_checksum_known_value(self):
        # RFC 1071 example words 0x0001 0xf203 0xf4f5 0xf6f7 → checksum 0x220d
        assert icmp.checksum(bytes.fromhex("0001f203f4f5f6f7")) == 0x220D

    def test_v4_echo_checksum_verifies(self):
        pkt = icmp.build_echo(socket.AF_INET, 0x1234, 7, b"payload!")
        assert pkt[0] == 8 and icmp.checksum(pkt) == 0

    def test_v6_echo_leaves_checksum_to_kernel(self):
        pkt = icmp.build_echo(socket.AF_INET6, 1, 2, b"x")
        assert pkt[0] == 128 and pkt[2:4] == b"\x00\x00"

    def test_strip_ip_header(self):
        msg = bytes([0, 0]) + bytes(6)
        assert icmp.strip_ip_header(_ipv4_header(6) + msg, socket.AF_INET) == msg
        assert icmp.strip_ip_header(msg, socket.AF_INET) == msg  # Linux dgram: no header
        assert icmp.strip_ip_header(msg, socket.AF_INET6) == msg

    def test_is_reply_matches_seq_and_token(self):
        token = b"T" * 8
        reply = struct.pack("!BBHHH", 0, 0, 0, 999, 5) + token
        assert icmp.is_reply(reply, socket.AF_INET, 5, token)
        assert not icmp.is_reply(reply, socket.AF_INET, 6, token)
        assert not icmp.is_reply(reply, socket.AF_INET, 5, b"X" * 8)
        request = struct.pack("!BBHHH", 128, 0, 0, 1, 5) + token  # own request on loopback
        assert not icmp.is_reply(request, socket.AF_INET6, 5, token)

    def test_quoted_seq_v4_and_v6(self):
        inner_v4 = _ipv4_header() + struct.pack("!BBHHH", 8, 0, 0, 1, 321)
        exceeded_v4 = struct.pack("!BBHI", 11, 0, 0, 0) + inner_v4
        assert icmp._quoted_seq(exceeded_v4, socket.AF_INET) == 321
        inner_v6 = bytes(40) + struct.pack("!BBHHH", 128, 0, 0, 1, 654)
        exceeded_v6 = struct.pack("!BBHI", 3, 0, 0, 0) + inner_v6
        assert icmp._quoted_seq(exceeded_v6, socket.AF_INET6) == 654

    def test_open_socket_prefers_dgram_then_raw(self):
        calls = []

        def factory(family, kind, proto):
            calls.append(kind)
            if kind == socket.SOCK_DGRAM:
                raise PermissionError
            return MagicMock()

        with patch("xping.diagnostics.icmp.socket.socket", side_effect=factory):
            _sock, mode = icmp.open_socket(socket.AF_INET)
        assert calls == [socket.SOCK_DGRAM, socket.SOCK_RAW] and mode == "raw"

    def test_open_socket_none_when_denied(self):
        with patch("xping.diagnostics.icmp.socket.socket", side_effect=PermissionError):
            assert icmp.open_socket(socket.AF_INET) is None
            assert icmp.echo("1.1.1.1", 1, 0.1) is None
            assert icmp.probe("1.1.1.1", 1, 1, 0.1) is None


class TestIcmpEcho:
    def _sock(self, replies):
        sock = MagicMock()
        sock.recvfrom.side_effect = replies
        return sock

    def test_echo_matches_reply_with_macos_ip_header(self):
        sent = {}
        sock = MagicMock()

        def sendto(pkt, _addr):
            sent["pkt"] = pkt

        def recvfrom(_n, *_flags):
            req = sent["pkt"]
            reply = bytes([0]) + req[1:]
            return _ipv4_header() + reply, ("1.1.1.1", 0)

        sock.sendto.side_effect = sendto
        sock.recvfrom.side_effect = recvfrom
        with (
            patch("xping.diagnostics.icmp.open_socket", return_value=(sock, "dgram")),
            patch("xping.diagnostics.icmp.select.select", return_value=([sock], [], [])),
        ):
            rtt = icmp.echo("1.1.1.1", 3, 1.0)
        assert rtt is not None and rtt >= 0

    def test_probe_reports_time_exceeded_router(self):
        sent = {}
        sock = MagicMock()
        sock.sendto.side_effect = lambda pkt, _a: sent.setdefault("pkt", pkt)

        def recvfrom(_n, *_flags):
            quoted = _ipv4_header() + sent["pkt"][:8]
            return _ipv4_header() + struct.pack("!BBHI", 11, 0, 0, 0) + quoted, ("10.0.0.1", 0)

        sock.recvfrom.side_effect = recvfrom
        with (
            patch("xping.diagnostics.icmp.open_socket", return_value=(sock, "raw")),
            patch("xping.diagnostics.icmp.select.select", return_value=([sock], [], [])),
        ):
            responder, rtt = icmp.probe("1.1.1.1", 2, 4242, 1.0)
        assert responder == "10.0.0.1" and rtt >= 0
        sock.setsockopt.assert_any_call(socket.IPPROTO_IP, socket.IP_TTL, 2)

    def test_linux_error_queue_offender(self):
        """IP_RECVERR: sock_extended_err (16 bytes) + sockaddr_in of the router."""
        seq = 77
        original = struct.pack("!BBHHH", 8, 0, 0, 1, seq)
        offender = struct.pack("=HH4s8x", socket.AF_INET, 0, socket.inet_aton("192.0.2.9"))
        cmsg = struct.pack("=IBBBBII", 113, 2, 11, 0, 0, 0, 0) + offender
        sock = MagicMock()
        sock.recvmsg.return_value = (original, [(0, 11, cmsg)], 0, None)
        assert icmp._read_error_queue(sock, socket.AF_INET, seq) == "192.0.2.9"
        assert icmp._read_error_queue(sock, socket.AF_INET, seq + 1) is None


# ── IPv6 command variants ─────────────────────────────────────────────────────


class TestIpv6Commands:
    @pytest.mark.parametrize(
        ("system", "expected"),
        [
            ("linux", ["ping", "-6", "-c", "1", "-W", "2", "2001:db8::1"]),
            ("darwin", ["ping6", "-c", "1", "2001:db8::1"]),
            ("windows", ["ping", "-6", "-n", "1", "-w", "2000", "2001:db8::1"]),
        ],
    )
    def test_ping_command(self, system, expected):
        from xping.diagnostics.platform_cmds import ping_command

        with patch("xping.diagnostics.platform_cmds.system_name", return_value=system):
            assert ping_command("2001:db8::1", 2.0) == expected

    def test_trace_command_variants(self):
        from xping.diagnostics.platform_cmds import trace_command

        with patch("xping.diagnostics.platform_cmds.trace_tool", return_value="traceroute6"):
            assert trace_command("2001:db8::1", 5, 1)[0] == "traceroute6"
        with patch("xping.diagnostics.platform_cmds.trace_tool", return_value="traceroute"):
            assert trace_command("2001:db8::1", 5, 1)[:2] == ["traceroute", "-6"]
        with patch("xping.diagnostics.platform_cmds.trace_tool", return_value="tracert"):
            assert trace_command("2001:db8::1", 5, 1)[:2] == ["tracert", "-6"]

    def test_mtu_probe_command_ipv6(self):
        from xping.diagnostics.platform_cmds import mtu_probe_command

        with patch("xping.diagnostics.platform_cmds.system_name", return_value="linux"):
            assert mtu_probe_command("2001:db8::1", 1400, 2)[:4] == ["ping", "-6", "-M", "do"]
        with patch("xping.diagnostics.platform_cmds.system_name", return_value="darwin"):
            assert mtu_probe_command("2001:db8::1", 1400, 2)[:2] == ["ping6", "-m"]
        with patch("xping.diagnostics.platform_cmds.system_name", return_value="windows"):
            with pytest.raises(ValueError):
                mtu_probe_command("2001:db8::1", 1400, 2)

    @pytest.mark.parametrize(
        ("line", "ip", "host"),
        [
            (" 1  2001:db8::1  0.512 ms", "2001:db8::1", None),
            (" 2  rtr.example.net (2001:db8::2)  1.2 ms", "2001:db8::2", "rtr.example.net"),
            (" 3  gw.example (10.0.0.1)  3.1 ms", "10.0.0.1", "gw.example"),
        ],
    )
    def test_trace_line_ipv6(self, line, ip, host):
        from xping.diagnostics.platform_cmds import _parse_traceroute_line

        _ttl, rtts, got_ip, got_host = _parse_traceroute_line(line)
        assert got_ip == ip and got_host == host and rtts

    def test_windows_tracert_ipv6(self):
        from xping.diagnostics.platform_cmds import _parse_tracert_line

        _ttl, rtts, ip, _h = _parse_tracert_line("  1    <1 ms    <1 ms    <1 ms  2001:db8::1")
        assert ip == "2001:db8::1" and rtts == [1.0, 1.0, 1.0]

    def test_osdetect_reads_macos_hlim(self):
        from xping.diagnostics.osdetect import _extract_ttl

        assert _extract_ttl("16 bytes from ::1, icmp_seq=0 hlim=57 time=0.07 ms") == 57

    def test_mtu_ipv6_overhead(self):
        from xping.models.mtu import ICMPV6_OVERHEAD_BYTES, MtuResult

        r = MtuResult(host="h", path_mtu=1500, overhead=ICMPV6_OVERHEAD_BYTES)
        assert r.max_payload == 1452

    def test_http_connects_to_resolved_address(self):
        from xping.diagnostics import http as http_diag

        conn = MagicMock()
        resp = MagicMock(status=200, reason="OK", version=11)
        resp.getheaders.return_value = []
        resp.getheader.return_value = None
        resp.read.return_value = b""
        conn.getresponse.return_value = resp
        with (
            patch.object(http_diag.http.client, "HTTPConnection", return_value=conn),
            patch.object(http_diag.socket, "create_connection") as create,
        ):
            d = http_diag._one_request("http://[2001:db8::5]:8080/", 1.0)
            conn._create_connection(("2001:db8::5", 8080), 1.0)
        assert d["ip"] == "2001:db8::5"
        create.assert_called_once_with(("2001:db8::5", 8080), 1.0)


class TestNativeTrace:
    def test_icmp_trace_hop_builds_hop(self):
        from xping.diagnostics import trace as trace_diag

        answers = [("10.0.0.1", 1.5), (None, -1.0), ("10.0.0.1", 2.5)]
        with (
            patch.object(trace_diag.icmp, "probe", side_effect=answers),
            patch.object(trace_diag, "_reverse", return_value="gw.local"),
        ):
            hop = trace_diag._icmp_trace_hop("1.1.1.1", 1, probes=3)
        assert hop.ip == "10.0.0.1" and hop.host == "gw.local" and hop.rtts[1] == -1.0

    def test_native_hop_falls_back_to_raw_udp_for_ipv4_only(self):
        from xping.diagnostics import trace as trace_diag
        from xping.models.trace import Hop

        raw = Hop(ttl=1, host=None, ip="10.0.0.1", rtts=[1.0])
        with (
            patch.object(trace_diag, "_icmp_trace_hop", return_value=None),
            patch.object(trace_diag, "_raw_trace_hop", return_value=raw) as raw_hop,
        ):
            assert trace_diag._native_hop("1.1.1.1", 1, 1.0, 1) is raw
            assert trace_diag._native_hop("2001:db8::1", 1, 1.0, 1) is None
        raw_hop.assert_called_once()

    def test_parser_family_flags(self):
        from xping.cli.parser import build_parser

        args = build_parser().parse_args(["ping", "h", "-6"])
        assert args.ipv6 and not args.ipv4
        with pytest.raises(SystemExit):
            build_parser().parse_args(["ping", "h", "-4", "-6"])
