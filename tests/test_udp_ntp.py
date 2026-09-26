"""xping udp and xping ntp."""

import json
import socket
import threading
from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.cli.verdict import evaluate
from xping.diagnostics import ntp as ntp_diag
from xping.diagnostics import udp as udp_diag
from xping.diagnostics.check import load_config
from xping.exporters.csv import export_csv
from xping.exporters.json import export_json
from xping.models.ntp import NtpResult, NtpSample
from xping.models.udp import UdpAttempt, UdpResult

# ── ntp ───────────────────────────────────────────────────────────────────────


def test_ntp_timestamp_roundtrip():
    t = 1790415060.123456
    assert abs(ntp_diag.from_ntp(ntp_diag.to_ntp(t)) - t) < 1e-6


def test_offset_and_delay_math():
    # server clock 0.5 s ahead, 40 ms each way, 10 ms processing
    t1 = 1000.0
    t2, t3 = t1 + 0.5 + 0.040, t1 + 0.5 + 0.050
    t4 = t1 + 0.090
    offset, delay = ntp_diag.offset_delay(t1, t2, t3, t4)
    assert offset == pytest.approx(500.0) and delay == pytest.approx(80.0)


def _reply(sent: bytes, stratum=2, ref=b"\xc0\x00\x02\x01", mode=4, leap=0, origin=None):
    first = (leap << 6) | (4 << 3) | mode
    body = bytes([first, stratum, 6, 0xEC]) + b"\x00" * 8 + ref + b"\x00" * 8
    body += origin if origin is not None else sent[40:48]
    return body + ntp_diag.to_ntp(1000.5) + ntp_diag.to_ntp(1000.51)


def test_parse_reply_fields_and_validation():
    sent = ntp_diag.request_packet(1000.0)
    fields = ntp_diag.parse_reply(_reply(sent), sent)
    assert fields["stratum"] == 2 and fields["reference"] == "192.0.2.1" and fields["leap"] == 0
    assert ntp_diag.parse_reply(_reply(sent, stratum=1, ref=b"GPS\x00"), sent)["reference"] == "GPS"
    assert ntp_diag.parse_reply(_reply(sent, stratum=0, ref=b"RATE"), sent)["reference"] == "KoD RATE"
    with pytest.raises(ValueError, match="mode"):
        ntp_diag.parse_reply(_reply(sent, mode=3), sent)
    with pytest.raises(ValueError, match="match"):
        ntp_diag.parse_reply(_reply(sent, origin=b"\x00" * 8), sent)
    with pytest.raises(ValueError, match="short"):
        ntp_diag.parse_reply(b"\x24" * 20, sent)


def test_request_packet_is_client_mode_v4():
    packet = ntp_diag.request_packet(1000.0)
    assert len(packet) == 48 and packet[0] == 0x23


def test_ntp_takes_lowest_delay_sample():
    answers = iter([
        ({"leap": 0, "version": 4, "stratum": 2, "reference": "10.0.0.1"}, 40.0, 300.0),
        TimeoutError(),
        ({"leap": 0, "version": 4, "stratum": 2, "reference": "10.0.0.1"}, 3.0, 20.0),
    ])

    def fake(ip, timeout, clock=None):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    with (
        patch.object(ntp_diag, "resolve", return_value="192.0.2.5"),
        patch.object(ntp_diag, "query_once", side_effect=fake),
        patch.object(ntp_diag.time, "sleep"),
    ):
        result = ntp_diag.ntp("time.test", count=3, quiet=True)
    assert result.offset_ms == 3.0 and result.delay_ms == 20.0 and result.synchronized
    assert [s.error for s in result.samples] == [None, "timeout", None]
    assert evaluate(result) == []
    assert evaluate(result, type("O", (), {"max_offset": 2})()) != []


def test_ntp_no_reply_and_unsynchronised():
    with (
        patch.object(ntp_diag, "resolve", return_value="192.0.2.5"),
        patch.object(ntp_diag, "query_once", side_effect=TimeoutError),
        patch.object(ntp_diag.time, "sleep"),
    ):
        result = ntp_diag.ntp("time.test", count=2, quiet=True)
    assert result.error == "no reply from time.test (UDP 123)" and evaluate(result)
    unsync = NtpResult("s", stratum=16, leap=3, samples=[NtpSample(1, 1.0, 5.0)])
    assert "not synchronised" in evaluate(unsync)[0].message


def test_ntp_exports():
    r = NtpResult("s", ip="1.2.3.4", stratum=2, leap=0, samples=[NtpSample(1, -1.5, 20.0)])
    data = json.loads(export_json(r))
    assert data["offset_ms"] == -1.5 and data["synchronized"] is True
    assert export_csv(r).splitlines()[0] == "seq,offset_ms,delay_ms,error"


# ── udp ───────────────────────────────────────────────────────────────────────


def test_probe_selection_and_payloads():
    assert udp_diag.probe_for(53) == "dns" and udp_diag.probe_for(123) == "ntp"
    assert udp_diag.probe_for(161) == "snmp" and udp_diag.probe_for(9999) == "empty"
    assert udp_diag.probe_for(53, "empty") == "empty"
    assert udp_diag.payload("snmp").hex() == (
        "302902010104067075626c6963a01c020400000001020100020100300e300c06082b060102010101000500"
    )
    dns = udp_diag.payload("dns")
    assert dns[2:4] == b"\x01\x00" and dns.endswith(b"\x00\x00\x02\x00\x01")  # root NS query
    assert len(udp_diag.payload("ntp")) == 48 and udp_diag.payload("empty") == b""
    assert udp_diag.payload("dns", "dead") == b"\xde\xad"


def test_describe_reply():
    dns = b"\x12\x34\x81\x80\x00\x01\x00\x0d\x00\x00\x00\x00"
    assert udp_diag.describe_reply("dns", dns) == "DNS server replied NOERROR, 13 answer(s)"
    assert udp_diag.describe_reply("ntp", b"\x24\x02" + b"\x00" * 46) == "NTP server, stratum 2"
    assert udp_diag.describe_reply("empty", b"abc") == "3 bytes"


@pytest.fixture
def udp_server():
    """A local UDP socket; replies when .reply is set, stays silent otherwise."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2)
    state = {"reply": b"pong", "stop": False}

    def serve():
        while not state["stop"]:
            try:
                data, addr = sock.recvfrom(2048)
            except OSError:
                return
            if state["reply"] is not None:
                sock.sendto(state["reply"], addr)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield sock.getsockname()[1], state
    state["stop"] = True
    sock.close()


def test_udp_open_against_local_server(udp_server):
    port, _ = udp_server
    result = udp_diag.udp("127.0.0.1", port, count=2, interval=0, timeout=1, quiet=True)
    assert result.state == "open" and result.replies == 2 and evaluate(result) == []
    assert result.attempts[0].reply_bytes == 4


def test_udp_silent_service_is_no_response(udp_server):
    port, state = udp_server
    state["reply"] = None
    result = udp_diag.udp("127.0.0.1", port, count=1, timeout=0.2, quiet=True)
    assert result.state == "no-response" and "filtered" in evaluate(result)[0].message


def test_udp_closed_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listens now: the kernel answers port unreachable
    result = udp_diag.udp("127.0.0.1", port, count=1, timeout=1, quiet=True)
    assert result.state in ("closed", "no-response")  # some sandboxes drop the ICMP error
    assert evaluate(result)


def test_udp_state_precedence_and_exports():
    r = UdpResult("h", 53, ip="1.2.3.4", probe="dns", attempts=[
        UdpAttempt(1, "no-response"), UdpAttempt(2, "open", 12.0, 30, "DNS server replied"),
    ])
    assert r.state == "open" and r.avg_rtt_ms == 12.0
    assert UdpResult("h", 1, attempts=[UdpAttempt(1, "no-response"), UdpAttempt(2, "closed")]).state == "closed"
    assert json.loads(export_json(r))["state"] == "open"
    assert export_csv(r).splitlines()[0] == "seq,state,rtt_ms,reply_bytes,detail"
    assert evaluate(r, type("O", (), {"max_latency": 5})())[0].threshold


def test_parser_and_check_types(tmp_path):
    parser = build_parser()
    args = parser.parse_args(["udp", "h", "161", "--payload", "de ad", "--watch"])
    assert args.payload == "dead" and args.probe == "auto" and args.every == 5.0
    with pytest.raises(SystemExit):
        parser.parse_args(["udp", "h", "53", "--payload", "xyz"])
    assert parser.parse_args(["ntp"]).server == "pool.ntp.org"
    assert parser.parse_args(["ntp", "time.test", "--max-offset", "250"]).max_offset == 250
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"checks": [
        {"type": "udp", "host": "1.1.1.1", "port": 53},
        {"type": "ntp", "max_offset": 500},
    ]}))
    udp_entry, ntp_entry = load_config(str(path))
    assert udp_entry["name"] == "udp 1.1.1.1" and ntp_entry["server"] == "pool.ntp.org"


def test_cmd_udp_watch_mode(monkeypatch):
    from xping.cli import commands

    seen = {}

    def fake_watch(target, check, probe, **kw):
        seen.update(target=target, check=check)

    monkeypatch.setattr(commands, "watch", fake_watch)
    commands.cmd_udp(build_parser().parse_args(["udp", "dns.test", "53", "--until-up"]))
    assert seen == {"target": "dns.test:53/udp", "check": "udp"}


def test_ntp_query_once_against_local_server():
    """End to end over a real socket: a fake server that echoes the
    transmit stamp as originate and claims to be 0.25 s ahead."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    def serve():
        data, addr = sock.recvfrom(512)
        t1 = ntp_diag.from_ntp(data[40:48])
        reply = bytes([0x24, 2, 6, 0xEC]) + b"\x00" * 8 + b"\x0a\x00\x00\x01" + b"\x00" * 8
        reply += data[40:48] + ntp_diag.to_ntp(t1 + 0.25) + ntp_diag.to_ntp(t1 + 0.25)
        sock.sendto(reply, addr)

    threading.Thread(target=serve, daemon=True).start()
    with patch.object(ntp_diag, "NTP_PORT", port):
        fields, offset, delay = ntp_diag.query_once("127.0.0.1", 2)
    sock.close()
    assert fields["stratum"] == 2 and offset == pytest.approx(250, abs=30)
