"""
xping.diagnostics.dnssec — is a domain signed with DNSSEC, and does it
validate?

Three raw queries to a validating resolver, with the EDNS0 "DO" bit so
signatures are returned:

  DS <domain>    at the parent: is DNSSEC switched on at the registrar?
  SOA <domain>   are the zone's answers signed (RRSIG)? did the resolver
                 validate them (AD flag)?
  SOA <domain>   again with "CD" (checking disabled) when the first one
                 fails with SERVFAIL: if it then works, the signatures
                 are broken ("bogus") and validating resolvers — most
                 ISPs, 1.1.1.1, 8.8.8.8 — cannot resolve the domain at all.

The validating resolvers are Cloudflare (1.1.1.1), then Google (8.8.8.8).
"""

from __future__ import annotations

import os
import socket
import struct

from xping.models.dnscheck import DnsCheckItem

VALIDATING_RESOLVERS = ("1.1.1.1", "8.8.8.8")
TYPE_SOA, TYPE_DS, TYPE_RRSIG, TYPE_DNSKEY, TYPE_OPT = 6, 43, 46, 48, 41
_FLAG_AD, _FLAG_CD, _FLAG_RD, _FLAG_TC = 0x0020, 0x0010, 0x0100, 0x0200
_RCODES = {0: "NOERROR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}


def build_query(name: str, qtype: int, cd: bool = False, ident: int | None = None) -> bytes:
    """A recursive query with an EDNS0 OPT record (4096-byte UDP, DO bit)."""
    ident = int.from_bytes(os.urandom(2), "big") if ident is None else ident
    flags = _FLAG_RD | (_FLAG_CD if cd else 0)
    header = struct.pack("!HHHHHH", ident, flags, 1, 0, 0, 1)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.strip(".").split(".") if p)
    question = qname + b"\x00" + struct.pack("!HH", qtype, 1)
    opt = b"\x00" + struct.pack("!HHIH", TYPE_OPT, 4096, 0x00008000, 0)  # DO = 1
    return header + question + opt


def _skip_name(data: bytes, pos: int) -> int:
    while pos < len(data):
        length = data[pos]
        if length == 0:
            return pos + 1
        if length & 0xC0 == 0xC0:  # compression pointer
            return pos + 2
        pos += length + 1
    raise ValueError("truncated name")


def parse_response(data: bytes, ident: int | None = None) -> dict:
    """rcode, AD/TC flags and the count of each record type in the answer."""
    if len(data) < 12:
        raise ValueError("short DNS response")
    rid, flags, qdcount, ancount = struct.unpack("!HHHH", data[:8])
    if ident is not None and rid != ident:
        raise ValueError("response ID mismatch")
    pos = 12
    for _ in range(qdcount):
        pos = _skip_name(data, pos) + 4
    types: dict[int, int] = {}
    for _ in range(ancount):
        pos = _skip_name(data, pos)
        rtype, _cls, _ttl, rdlen = struct.unpack("!HHIH", data[pos : pos + 10])
        types[rtype] = types.get(rtype, 0) + 1
        pos += 10 + rdlen
    return {
        "rcode": _RCODES.get(flags & 0x000F, f"RCODE{flags & 0x000F}"),
        "ad": bool(flags & _FLAG_AD),
        "tc": bool(flags & _FLAG_TC),
        "types": types,
    }


def ask(name: str, qtype: int, server: str, cd: bool = False, timeout: float = 3.0) -> dict:
    """One query over UDP, retried over TCP when the answer is truncated."""
    ident = int.from_bytes(os.urandom(2), "big")
    packet = build_query(name, qtype, cd, ident)
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (server, 53))
        data, _ = sock.recvfrom(4096)
    answer = parse_response(data, ident)
    if answer["tc"]:
        with socket.create_connection((server, 53), timeout=timeout) as sock:
            sock.sendall(struct.pack("!H", len(packet)) + packet)
            length = struct.unpack("!H", _recv_exact(sock, 2))[0]
            answer = parse_response(_recv_exact(sock, length), ident)
    return answer


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = b""
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ValueError("connection closed")
        chunks += chunk
    return chunks


def evaluate(ds: dict, soa: dict, soa_cd: dict | None) -> DnsCheckItem:
    """The DNSSEC check item from the three answers."""
    has_ds = ds["rcode"] == "NOERROR" and ds["types"].get(TYPE_DS, 0) > 0
    if soa["rcode"] == "SERVFAIL" and soa_cd is not None and soa_cd["rcode"] == "NOERROR":
        return DnsCheckItem(
            "DNSSEC",
            "fail",
            "Validation FAILS (bogus signatures) — validating resolvers cannot resolve this domain",
        )
    signed = soa["types"].get(TYPE_RRSIG, 0) > 0
    if has_ds and soa["ad"]:
        return DnsCheckItem("DNSSEC", "ok", "Signed and validated (DS at parent, AD flag)")
    if has_ds:
        return DnsCheckItem("DNSSEC", "warn", "DS record present, but the answer was not validated")
    if signed:
        return DnsCheckItem(
            "DNSSEC",
            "warn",
            "Zone is signed but has no DS record at the parent — DNSSEC is not active",
        )
    return DnsCheckItem("DNSSEC", "info", "Not signed — DNSSEC is not enabled")


def dnssec_check(domain: str, timeout: float = 3.0) -> DnsCheckItem:
    last_error = "no validating resolver answered"
    for server in VALIDATING_RESOLVERS:
        try:
            ds = ask(domain, TYPE_DS, server, timeout=timeout)
            soa = ask(domain, TYPE_SOA, server, timeout=timeout)
            soa_cd = (
                ask(domain, TYPE_SOA, server, cd=True, timeout=timeout)
                if soa["rcode"] == "SERVFAIL"
                else None
            )
        except (OSError, ValueError) as exc:
            last_error = f"{server}: {exc}" if str(exc) else f"{server}: timeout"
            continue
        return evaluate(ds, soa, soa_cd)
    return DnsCheckItem("DNSSEC", "unknown", f"Not verified ({last_error})")
