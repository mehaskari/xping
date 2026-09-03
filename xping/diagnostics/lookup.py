"""
xping.lookup — DNS lookup with optional custom server (like dig @8.8.8.8).
Falls back to raw UDP when dig is unavailable.
"""

import socket
import struct
import subprocess

from xping.diagnostics.deps import warn_missing
from xping.models.lookup import DnsResult
from xping.render import c, section_header, kv, BRAND_TEAL, BRAND_INDIGO, BOLD
from xping.render.errors import error
from xping.render.views import lookup as lookup_view


# ── dig-based queries ──────────────────────────────────────────────────────────

def _dig_query(host: str, rtype: str, server: str | None = None) -> str | None:
    cmd = ["dig", "+noall", "+answer", "+ttl"]
    if server:
        cmd.append(f"@{server}")
    cmd += [rtype, host]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _parse_dig_a(output: str) -> tuple[list[str], int | None]:
    ips, ttl = [], None
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "A":
            ips.append(parts[4])
            try: ttl = int(parts[1])
            except ValueError: pass
    return ips, ttl


def _parse_dig_aaaa(output: str) -> list[str]:
    return [p.split()[4] for p in output.splitlines()
            if len(p.split()) >= 5 and p.split()[3] == "AAAA"]


def _parse_dig_mx(output: str) -> list[tuple[int, str]]:
    records = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[3] == "MX":
            try: records.append((int(parts[4]), parts[5].rstrip(".")))
            except (ValueError, IndexError): pass
    return sorted(records)


def _parse_dig_ns(output: str) -> list[str]:
    return [p.split()[4].rstrip(".") for p in output.splitlines()
            if len(p.split()) >= 5 and p.split()[3] == "NS"]


def _parse_dig_txt(output: str) -> list[str]:
    txts = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3] == "TXT":
            txts.append(" ".join(parts[4:]).strip('"'))
    return txts


def _parse_dig_cname(output: str) -> str | None:
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "CNAME":
            return parts[4].rstrip(".")
    return None


# ── Raw UDP DNS fallback ───────────────────────────────────────────────────────

def _build_dns_packet(qname: str, qtype: int) -> bytes:
    header = struct.pack("!HHHHHH", 0xAB12, 0x0100, 1, 0, 0, 0)
    q = b""
    for label in qname.rstrip(".").split("."):
        lb = label.encode()
        q += bytes([len(lb)]) + lb
    q += b"\x00" + struct.pack("!HH", qtype, 1)
    return header + q


def _parse_dns_response(data: bytes, qtype: int) -> list[str]:
    if len(data) < 12: return []
    ancount = struct.unpack("!H", data[6:8])[0]
    if not ancount: return []

    def read_name(buf: bytes, pos: int) -> tuple[str, int]:
        labels, jumped, orig = [], False, pos
        while pos < len(buf):
            if buf[pos] & 0xC0 == 0xC0:
                ptr = ((buf[pos] & 0x3F) << 8) | buf[pos + 1]
                if not jumped: orig = pos + 2
                pos, jumped = ptr, True
                continue
            length = buf[pos]; pos += 1
            if length == 0: break
            labels.append(buf[pos:pos+length].decode("ascii", errors="replace"))
            pos += length
        return ".".join(labels), (orig if jumped else pos)

    pos = 12
    for _ in range(struct.unpack("!H", data[4:6])[0]):
        while pos < len(data) and data[pos] != 0:
            if data[pos] & 0xC0 == 0xC0: pos += 2; break
            pos += data[pos] + 1
        else:
            pos += 1
        pos += 4

    results = []
    for _ in range(ancount):
        if pos >= len(data): break
        _, pos = read_name(data, pos)
        if pos + 10 > len(data): break
        rtype, _, _, rdlen = struct.unpack("!HHIH", data[pos:pos+10])
        pos += 10
        rdata = data[pos:pos+rdlen]; pos += rdlen

        if rtype == 1 and len(rdata) == 4:
            results.append(socket.inet_ntoa(rdata))
        elif rtype == 28 and len(rdata) == 16:
            results.append(socket.inet_ntop(socket.AF_INET6, rdata))
        elif rtype in (2, 5):
            name, _ = read_name(data, pos - rdlen)
            results.append(name)
        elif rtype == 15 and len(rdata) >= 3:
            prio = struct.unpack("!H", rdata[:2])[0]
            mx_name, _ = read_name(data, pos - rdlen + 2)
            results.append(f"{prio} {mx_name}")
        elif rtype == 16:
            txt, i = [], 0
            while i < len(rdata):
                l = rdata[i]; i += 1
                txt.append(rdata[i:i+l].decode("utf-8", errors="replace"))
                i += l
            results.append(" ".join(txt))
    return results


def _raw_query(host: str, qtype: int, server: str = "8.8.8.8",
               timeout: float = 4.0) -> list[str]:
    packet = _build_dns_packet(host, qtype)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(packet, (server, 53))
            resp, _ = sock.recvfrom(4096)
        return _parse_dns_response(resp, qtype)
    except Exception:  # noqa: BLE001
        return []


def _socket_resolve(host: str) -> tuple[list[str], list[str]]:
    v4, v6 = [], []
    try:
        for info in socket.getaddrinfo(host, None):
            addr = info[4][0]
            if ":" in addr:
                if addr not in v6: v6.append(addr)
            else:
                if addr not in v4: v4.append(addr)
    except socket.gaierror:
        pass
    return v4, v6


# ── Main entry point ───────────────────────────────────────────────────────────

def lookup(host: str, full: bool = False, quiet: bool = False,
           server: str | None = None) -> DnsResult:
    """DNS lookup, optionally querying a custom *server* like dig @8.8.8.8."""
    result = DnsResult(host=host)

    if not quiet:
        print(section_header(f"DNS LOOKUP  {host}", "◑"))
        print(kv("Query", c(host, BRAND_TEAL, BOLD)))
        if server:
            print(kv("Server", c(f"@{server}", BRAND_INDIGO, BOLD)))
        print()

    # Try dig first
    test = _dig_query(host, "A", server)
    has_dig = test is not None or _dig_query(host, "A") is not None

    if has_dig:
        a_out = _dig_query(host, "A", server) or ""
        if a_out:
            result.ipv4, result.ttl = _parse_dig_a(a_out)
            cname_out = _dig_query(host, "CNAME", server) or ""
            result.cname = _parse_dig_cname(a_out + "\n" + cname_out)
        aaaa_out = _dig_query(host, "AAAA", server) or ""
        result.ipv6 = _parse_dig_aaaa(aaaa_out)
        mx_out = _dig_query(host, "MX", server) or ""
        result.mx = _parse_dig_mx(mx_out)
        ns_out = _dig_query(host, "NS", server) or ""
        result.ns = _parse_dig_ns(ns_out)
        if full:
            txt_out = _dig_query(host, "TXT", server) or ""
            result.txt = _parse_dig_txt(txt_out)
    else:
        # Fallback: raw UDP to requested server or 8.8.8.8
        dns_server = server or "8.8.8.8"
        if not quiet:
            warn_missing("dig", f"using raw UDP DNS → {dns_server}")
        result.ipv4 = _raw_query(host, 1, dns_server)
        result.ipv6 = _raw_query(host, 28, dns_server)
        mx_raw = _raw_query(host, 15, dns_server)
        for entry in mx_raw:
            parts = entry.split(" ", 1)
            if len(parts) == 2:
                try: result.mx.append((int(parts[0]), parts[1].rstrip(".")))
                except ValueError: pass
        result.ns = [n.rstrip(".") for n in _raw_query(host, 2, dns_server)]
        if full:
            result.txt = _raw_query(host, 16, dns_server)

    if not result.ipv4 and not result.ipv6:
        result.error = "No DNS records found"
        if not quiet:
            error(f"{result.error} for '{host}'")
        return result

    for ip in (result.ipv4 + result.ipv6)[:8]:
        try: result.reverse[ip] = socket.gethostbyaddr(ip)[0]
        except Exception: result.reverse[ip] = "—"

    if not quiet:
        lookup_view.print_result(result, full=full)
    return result
