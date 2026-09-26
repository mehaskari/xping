"""
xping.diagnostics.udp — is a UDP service answering?

UDP has no handshake, so the only proof that a service is there is a
reply. xping sends a request the service understands (chosen by port, or
set with --probe) on a connected socket and classifies each attempt:

  open         a reply came back
  closed       the host answered ICMP "port unreachable" (the socket
               reports ECONNREFUSED — WSAECONNRESET on Windows)
  no-response  nothing came back: the port is filtered, or a service
               that stays silent for this request

Probes:
  dns   a root "NS" query                 (port 53, 5353)
  ntp   an SNTP client request            (port 123)
  snmp  SNMPv2c GET sysDescr, "public"    (port 161)
  empty an empty datagram                 (anything else)
"""

from __future__ import annotations

import os
import socket
import struct
import time

from xping.diagnostics.ntp import request_packet
from xping.diagnostics.resolve import resolve
from xping.models.udp import CLOSED, NO_RESPONSE, OPEN, UdpAttempt, UdpResult
from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header
from xping.render.errors import resolve_error
from xping.render.views import udp as udp_view

PROBES = ("auto", "dns", "ntp", "snmp", "empty")
_PORT_PROBES = {53: "dns", 5353: "dns", 123: "ntp", 161: "snmp"}


def _tlv(tag: int, value: bytes) -> bytes:
    """One BER element (all lengths here are < 128, so short form)."""
    return bytes([tag, len(value)]) + value


# SNMPv2c GetRequest for sysDescr.0 (1.3.6.1.2.1.1.1.0), community "public"
_SYSDESCR_OID = bytes([0x2B, 6, 1, 2, 1, 1, 1, 0])
_SNMP_GET = _tlv(
    0x30,
    _tlv(0x02, b"\x01")  # version: 1 = v2c
    + _tlv(0x04, b"public")
    + _tlv(
        0xA0,  # GetRequest-PDU
        _tlv(0x02, b"\x00\x00\x00\x01")  # request-id
        + _tlv(0x02, b"\x00")  # error-status
        + _tlv(0x02, b"\x00")  # error-index
        + _tlv(0x30, _tlv(0x30, _tlv(0x06, _SYSDESCR_OID) + _tlv(0x05, b""))),
    ),
)


def _dns_probe() -> bytes:
    ident = os.urandom(2)
    return ident + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + b"\x00" + struct.pack("!HH", 2, 1)


def probe_for(port: int, probe: str = "auto") -> str:
    return _PORT_PROBES.get(port, "empty") if probe == "auto" else probe


def payload(kind: str, hex_payload: str | None = None) -> bytes:
    if hex_payload is not None:
        return bytes.fromhex(hex_payload)
    if kind == "dns":
        return _dns_probe()
    if kind == "ntp":
        return request_packet(time.time())
    if kind == "snmp":
        return _SNMP_GET
    return b""


def describe_reply(kind: str, data: bytes) -> str:
    """A short, human description of what answered."""
    if kind == "dns" and len(data) >= 12:
        rcode = data[3] & 0x0F
        answers = struct.unpack("!H", data[6:8])[0]
        names = {0: "NOERROR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}
        return f"DNS server replied {names.get(rcode, f'RCODE {rcode}')}, {answers} answer(s)"
    if kind == "ntp" and len(data) >= 48:
        return f"NTP server, stratum {data[1]}"
    if kind == "snmp" and data[:1] == b"\x30":
        return "SNMP agent replied (community 'public' accepted)"
    return f"{len(data)} bytes"


def _attempt(ip: str, port: int, data: bytes, kind: str, seq: int, timeout: float) -> UdpAttempt:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        started = time.perf_counter()
        try:
            sock.connect((ip, port))
            sock.send(data)
            reply = sock.recv(4096)
        except (TimeoutError, socket.timeout):
            return UdpAttempt(seq, NO_RESPONSE, detail="no reply")
        except (ConnectionRefusedError, ConnectionResetError):
            rtt = (time.perf_counter() - started) * 1000
            return UdpAttempt(seq, CLOSED, rtt, detail="ICMP port unreachable")
        except OSError as exc:
            return UdpAttempt(seq, NO_RESPONSE, detail=str(exc) or type(exc).__name__)
        rtt = (time.perf_counter() - started) * 1000
    return UdpAttempt(seq, OPEN, rtt, len(reply), describe_reply(kind, reply))


def udp(
    host: str,
    port: int,
    count: int = 3,
    timeout: float = 2.0,
    interval: float = 0.5,
    probe: str = "auto",
    hex_payload: str | None = None,
    quiet: bool = False,
    family: int | None = None,
) -> UdpResult:
    kind = "hex" if hex_payload is not None else probe_for(port, probe)
    result = UdpResult(host=host, port=port, probe=kind)
    try:
        result.ip = resolve(host, family)
    except socket.gaierror as exc:
        if not quiet:
            resolve_error(host, exc)
        result.error = f"cannot resolve '{host}'"
        return result

    if not quiet:
        print(section_header(f"UDP PROBE  {host}:{port}", "◌"))
        print(kv("Target", c(host, BRAND_TEAL, BOLD)))
        if result.ip != host:
            print(kv("IP", c(result.ip, BRAND_INDIGO)))
        print(kv("Probe", kind))
        print(kv("Attempts", str(count)))
        print()

    for seq in range(1, count + 1):
        started = time.perf_counter()
        attempt = _attempt(result.ip, port, payload(kind, hex_payload), kind, seq, timeout)
        result.attempts.append(attempt)
        if not quiet:
            udp_view.print_attempt(attempt, count)
        if seq < count:
            remaining = interval - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)

    if not quiet:
        udp_view.print_summary(result)
    return result
