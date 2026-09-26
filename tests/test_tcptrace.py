"""trace --tcp: TCP SYN traceroute (ICMP quoting, Linux error queue, driver)."""

import socket
import struct
from unittest.mock import patch

from xping.cli.parser import build_parser
from xping.diagnostics import tcptrace
from xping.diagnostics import trace as trace_diag

SOL_IP = getattr(socket, "SOL_IP", 0)  # missing on some Windows builds


def _ipv4_header(proto=socket.IPPROTO_TCP, src="10.0.0.2", dst="140.82.121.4"):
    return struct.pack(
        "!BBHHHBBH4s4s", 0x45, 0, 40, 1, 0, 1, proto, 0,
        socket.inet_aton(src), socket.inet_aton(dst),
    )


def _time_exceeded_v4(sport, dport, proto=socket.IPPROTO_TCP):
    tcp = struct.pack("!HHI", sport, dport, 12345)
    return bytes([11, 0, 0, 0, 0, 0, 0, 0]) + _ipv4_header(proto) + tcp


def test_quoted_ports_ipv4():
    assert tcptrace.quoted_ports(_time_exceeded_v4(50123, 443), socket.AF_INET) == (50123, 443)
    # destination unreachable quotes the same way
    unreach = bytes([3]) + _time_exceeded_v4(1, 2)[1:]
    assert tcptrace.quoted_ports(unreach, socket.AF_INET) == (1, 2)


def test_quoted_ports_ignores_other_messages():
    udp = _time_exceeded_v4(50123, 443, proto=socket.IPPROTO_UDP)
    assert tcptrace.quoted_ports(udp, socket.AF_INET) is None
    echo_reply = bytes([0]) + _time_exceeded_v4(1, 2)[1:]
    assert tcptrace.quoted_ports(echo_reply, socket.AF_INET) is None
    assert tcptrace.quoted_ports(b"\x0b\x00", socket.AF_INET) is None


def test_quoted_ports_ipv6():
    ipv6 = bytes([0x60, 0, 0, 0, 0, 20, socket.IPPROTO_TCP, 1]) + b"\x00" * 32
    msg = bytes([3, 0, 0, 0, 0, 0, 0, 0]) + ipv6 + struct.pack("!HH", 40000, 22)
    assert tcptrace.quoted_ports(msg, socket.AF_INET6) == (40000, 22)
    assert tcptrace.quoted_ports(bytes([11]) + msg[1:], socket.AF_INET6) is None  # v4 type


def test_offender_from_linux_extended_error():
    ee = b"\x00" * 16  # struct sock_extended_err
    v4 = ee + struct.pack("!HH4s8x", socket.AF_INET, 0, socket.inet_aton("192.0.2.1"))
    assert tcptrace._offender([(SOL_IP, 11, v4)], socket.AF_INET) == "192.0.2.1"
    v6 = ee + struct.pack("!HHI16sI", socket.AF_INET6, 0, 0,
                          socket.inet_pton(socket.AF_INET6, "2001:db8::1"), 0)
    sol_ipv6 = getattr(socket, "SOL_IPV6", 41)
    assert tcptrace._offender([(sol_ipv6, 25, v6)], socket.AF_INET6) == "2001:db8::1"
    assert tcptrace._offender([(SOL_IP, 11, b"short")], socket.AF_INET) is None


class FakeTracer:
    def __init__(self, answers):
        self.answers = list(answers)
        self.closed = False

    def probe(self, ttl, timeout=2.0):
        return self.answers.pop(0)

    def close(self):
        self.closed = True


def test_tcp_hop_builds_hop():
    tracer = FakeTracer([("10.0.0.1", 1.5), (None, -1.0), ("10.0.0.1", 2.5)])
    with patch.object(trace_diag, "_reverse", return_value="gw.local"):
        hop = trace_diag._tcp_trace_hop(tracer, 1, 1.0, 3)
    assert hop.ip == "10.0.0.1" and hop.host == "gw.local" and not hop.timeout
    assert hop.avg_rtt == 2.0


def test_trace_tcp_stops_at_destination_and_closes():
    answers = [("10.0.0.1", 1.0), (None, -1.0), ("93.184.216.34", 20.0)]
    tracer = FakeTracer(answers)
    with (
        patch.object(trace_diag, "resolve", return_value="93.184.216.34"),
        patch.object(trace_diag.tcptrace, "supported", return_value=True),
        patch.object(trace_diag.tcptrace, "TcpTracer", return_value=tracer) as cls,
        patch.object(trace_diag, "_reverse", return_value=None),
        patch.object(trace_diag, "_native_hop") as icmp_hop,
    ):
        hops = trace_diag.trace("example.com", probes=1, quiet=True, tcp_port=443)
    cls.assert_called_once_with("93.184.216.34", 443)
    icmp_hop.assert_not_called()
    assert [h.ttl for h in hops] == [1, 2, 3] and hops[1].timeout
    assert hops[-1].ip == "93.184.216.34" and tracer.closed


def test_trace_tcp_unsupported_platform(capsys):
    with (
        patch.object(trace_diag, "resolve", return_value="1.2.3.4"),
        patch.object(trace_diag.tcptrace, "supported", return_value=False),
    ):
        assert trace_diag.trace("h", tcp_port=443) == []
    assert "needs Linux or macOS" in capsys.readouterr().err


def test_trace_tcp_without_icmp_listener(capsys):
    with (
        patch.object(trace_diag, "resolve", return_value="1.2.3.4"),
        patch.object(trace_diag.tcptrace, "supported", return_value=True),
        patch.object(trace_diag.tcptrace, "TcpTracer", side_effect=OSError("no ICMP socket")),
    ):
        assert trace_diag.trace("h", tcp_port=443) == []
    assert "no ICMP socket" in capsys.readouterr().err


def test_parser_port_implies_tcp():
    from xping.cli import commands

    parser = build_parser()
    for argv, expected in (
        (["trace", "h"], None),
        (["trace", "h", "--tcp"], 443),
        (["trace", "h", "-T", "--port", "22"], 22),
        (["trace", "h", "--port", "8443"], 8443),
    ):
        args = parser.parse_args(argv)
        with patch.object(commands, "trace", return_value=[]) as run:
            commands.cmd_trace(args)
        assert run.call_args.kwargs["tcp_port"] == expected, argv


def test_linux_error_queue_probe_end_to_end():
    """On Linux, a real TTL-1 SYN toward a documentation address must come
    back from the first router via the error queue — or time out when the
    sandbox has no route. Either way it must not raise."""
    import sys

    if not sys.platform.startswith("linux"):
        return
    try:
        tracer = tcptrace.TcpTracer("192.0.2.1", 443)
    except OSError:
        return
    with tracer:
        responder, rtt = tracer.probe(1, timeout=0.5)
    assert (responder is None and rtt == -1.0) or rtt >= 0
