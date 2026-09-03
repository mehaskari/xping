"""
xping.diagnostics.rdns — Reverse DNS (PTR) lookup.
Primary: socket.gethostbyaddr() via the system resolver.
Fallback: manual DNS PTR query to 8.8.8.8 when the system resolver
          fails (e.g. the resolver doesn't handle in-addr.arpa).
"""

import socket
import struct

from xping.models.rdns import RdnsResult
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.views import rdns as rdns_view

_DNS_FALLBACK = "8.8.8.8"
_DNS_PORT = 53
_DNS_TIMEOUT = 4.0


def _is_ip(value: str) -> bool:
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, value)
            return True
        except OSError:
            continue
    return False


def _ptr_name(ip: str) -> str:
    """Build the in-addr.arpa / ip6.arpa name for reverse lookup."""
    try:
        socket.inet_pton(socket.AF_INET6, ip)
        # expand to full hex, reverse nibbles
        packed = socket.inet_pton(socket.AF_INET6, ip)
        hex_str = packed.hex()
        return ".".join(reversed(list(hex_str))) + ".ip6.arpa"
    except OSError:
        pass
    parts = ip.split(".")
    return ".".join(reversed(parts)) + ".in-addr.arpa"


def _dns_query_bytes(name: str, qtype: int = 12) -> bytes:
    """Build a minimal DNS query packet for *name* (qtype 12 = PTR)."""
    txid = 0x1234
    flags = 0x0100  # standard query, recursion desired
    header = struct.pack("!HHHHHH", txid, flags, 1, 0, 0, 0)
    qname = b""
    for part in name.rstrip(".").split("."):
        label = part.encode()
        qname += bytes([len(label)]) + label
    qname += b"\x00"
    question = qname + struct.pack("!HH", qtype, 1)
    return header + question


def _parse_ptr_response(data: bytes) -> list[str]:
    """Extract PTR name strings from a raw DNS response."""
    if len(data) < 12:
        return []
    ancount = struct.unpack("!H", data[6:8])[0]
    if not ancount:
        return []

    pos = 12
    # Skip question section
    while pos < len(data):
        if data[pos] == 0:
            pos += 1
            break
        if data[pos] & 0xC0 == 0xC0:
            pos += 2
            break
        pos += data[pos] + 1
    pos += 4  # QTYPE + QCLASS

    results = []
    for _ in range(ancount):
        if pos >= len(data):
            break
        # Skip name (may be pointer)
        if data[pos] & 0xC0 == 0xC0:
            pos += 2
        else:
            while pos < len(data) and data[pos] != 0:
                pos += data[pos] + 1
            pos += 1
        if pos + 10 > len(data):
            break
        rtype, _, _, rdlen = struct.unpack("!HHIH", data[pos:pos + 10])
        pos += 10
        if rtype == 12:  # PTR
            # decode the name in RDATA (may have pointers)
            name_parts = []
            rpos = pos
            while rpos < pos + rdlen and rpos < len(data):
                if data[rpos] & 0xC0 == 0xC0:
                    ptr = ((data[rpos] & 0x3F) << 8) | data[rpos + 1]
                    rpos = ptr
                    continue
                length = data[rpos]
                rpos += 1
                if length == 0:
                    break
                name_parts.append(data[rpos:rpos + length].decode("ascii", errors="replace"))
                rpos += length
            results.append(".".join(name_parts))
        pos += rdlen
    return results


def _fallback_ptr(ip: str) -> str | None:
    """Direct UDP DNS PTR query to 8.8.8.8 as fallback."""
    ptr_name = _ptr_name(ip)
    packet = _dns_query_bytes(ptr_name)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(_DNS_TIMEOUT)
            sock.sendto(packet, (_DNS_FALLBACK, _DNS_PORT))
            resp, _ = sock.recvfrom(512)
        names = _parse_ptr_response(resp)
        return names[0].rstrip(".") if names else None
    except Exception:  # noqa: BLE001
        return None


def rdns(ip: str, quiet: bool = False) -> RdnsResult:
    """Resolve *ip* to a hostname via its PTR record."""
    result = RdnsResult(ip=ip)

    if not quiet:
        print(section_header(f"REVERSE DNS  {ip}", "◐"))
        print(kv("Query", c(ip, BRAND_TEAL, BOLD)))
        print()

    if not _is_ip(ip):
        result.error = f"'{ip}' is not a valid IPv4 or IPv6 address"
        if not quiet:
            rdns_view.print_error(result)
        return result

    # Primary: system resolver
    try:
        hostname, aliases, addresses = socket.gethostbyaddr(ip)
        result.hostname = hostname
        result.aliases = aliases
        result.addresses = addresses
    except socket.herror:
        # Fallback: direct UDP query to 8.8.8.8
        hostname = _fallback_ptr(ip)
        if hostname:
            result.hostname = hostname
        else:
            result.error = f"No PTR record found for '{ip}'"
    except OSError as exc:
        result.error = f"Reverse lookup failed: {exc}"

    if not quiet:
        if result.error:
            rdns_view.print_error(result)
        else:
            rdns_view.print_result(result)
    return result
