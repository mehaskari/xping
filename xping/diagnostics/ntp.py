"""
xping.diagnostics.ntp — how far off is this machine's clock?

A minimal SNTP client (RFC 4330): one 48-byte UDP packet to port 123 per
sample. From the four timestamps (client send t1, server receive t2,
server send t3, client receive t4):

    offset = ((t2 - t1) + (t3 - t4)) / 2      server clock minus ours
    delay  = (t4 - t1) - (t3 - t2)            network round trip

Several samples are taken and the one with the lowest delay wins, because
network asymmetry is the main error in the offset.
"""

from __future__ import annotations

import os
import socket
import struct
import time

from xping.diagnostics.resolve import resolve
from xping.models.ntp import NtpResult, NtpSample
from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header
from xping.render.errors import resolve_error
from xping.render.views import ntp as ntp_view

NTP_PORT = 123
DEFAULT_SERVER = "pool.ntp.org"
_EPOCH_DELTA = 2208988800  # seconds from 1900-01-01 (NTP) to 1970-01-01 (Unix)


def to_ntp(unix: float) -> bytes:
    seconds = unix + _EPOCH_DELTA
    return struct.pack("!II", int(seconds), int((seconds % 1) * 2**32))


def from_ntp(data: bytes) -> float:
    seconds, fraction = struct.unpack("!II", data)
    return seconds - _EPOCH_DELTA + fraction / 2**32


def request_packet(transmit: float) -> bytes:
    """Client request: LI=0, VN=4, mode=3; the transmit timestamp is echoed
    back by the server as "originate", which proves the reply is ours."""
    return bytes([0x23]) + b"\x00" * 39 + to_ntp(transmit)


def parse_reply(data: bytes, sent: bytes) -> dict:
    """Header fields and server timestamps from a 48-byte reply. Raises
    ValueError for anything that is not a valid answer to *sent*."""
    if len(data) < 48:
        raise ValueError("short NTP reply")
    first = data[0]
    leap, version, mode = first >> 6, (first >> 3) & 0x07, first & 0x07
    if mode != 4:
        raise ValueError(f"unexpected NTP mode {mode}")
    if data[24:32] != sent[40:48]:
        raise ValueError("reply does not match our request")
    stratum = data[1]
    ref = data[12:16]
    if stratum == 0:
        reference = "KoD " + ref.decode("ascii", "replace").strip("\x00")  # kiss-o'-death
    elif stratum == 1:
        reference = ref.decode("ascii", "replace").strip("\x00") or None
    else:
        reference = socket.inet_ntoa(ref) if len(ref) == 4 else None
    return {
        "leap": leap,
        "version": version,
        "stratum": stratum,
        "reference": reference,
        "receive": from_ntp(data[32:40]),
        "transmit": from_ntp(data[40:48]),
    }


def offset_delay(t1: float, t2: float, t3: float, t4: float) -> tuple[float, float]:
    """(offset, delay) in milliseconds."""
    return ((t2 - t1) + (t3 - t4)) / 2 * 1000, ((t4 - t1) - (t3 - t2)) * 1000


def query_once(ip: str, timeout: float, clock=time.time) -> tuple[dict, float, float]:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        t1 = clock()
        # random low bits make the request unguessable for spoofed replies;
        # they shift the stamp by < 0.07 ms and only in the packet
        packet = request_packet(t1 + int.from_bytes(os.urandom(2), "big") * 1e-9)
        sock.sendto(packet, (ip, NTP_PORT))
        data, _ = sock.recvfrom(512)
        t4 = clock()
    fields = parse_reply(data, packet)
    offset, delay = offset_delay(t1, fields["receive"], fields["transmit"], t4)
    return fields, offset, delay


def ntp(
    server: str = DEFAULT_SERVER,
    count: int = 4,
    timeout: float = 2.0,
    quiet: bool = False,
    family: int | None = None,
) -> NtpResult:
    result = NtpResult(server=server)
    try:
        result.ip = resolve(server, family)
    except socket.gaierror as exc:
        if not quiet:
            resolve_error(server, exc)
        result.error = f"cannot resolve '{server}'"
        return result

    if not quiet:
        print(section_header(f"NTP CLOCK CHECK  {server}", "◷"))
        print(kv("Server", c(server, BRAND_TEAL, BOLD)))
        if result.ip != server:
            print(kv("IP", c(result.ip, BRAND_INDIGO)))
        print(kv("Samples", str(count)))
        print()

    for seq in range(1, count + 1):
        try:
            fields, offset, delay = query_once(result.ip, timeout)
        except (TimeoutError, socket.timeout):
            sample = NtpSample(seq, error="timeout")
        except (OSError, ValueError) as exc:
            sample = NtpSample(seq, error=str(exc) or type(exc).__name__)
        else:
            sample = NtpSample(seq, offset_ms=offset, delay_ms=delay)
            result.leap, result.version = fields["leap"], fields["version"]
            result.stratum, result.reference = fields["stratum"], fields["reference"]
        result.samples.append(sample)
        if not quiet:
            ntp_view.print_sample(sample, count)
        if seq < count:
            time.sleep(0.2)

    if not result.answered:
        errors = {s.error for s in result.samples}
        result.error = (
            f"no reply from {server} (UDP {NTP_PORT})"
            if errors <= {"timeout"}
            else "; ".join(sorted(e for e in errors if e))
        )
    if not quiet:
        ntp_view.print_summary(result)
    return result
