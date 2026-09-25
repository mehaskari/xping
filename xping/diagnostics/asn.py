"""IP → ASN / network operator, via Team Cymru's DNS interface.

Two TXT lookups per address, both over plain DNS (``dig`` or xping's raw
UDP resolver), so no extra dependency and no HTTP API key:

    1.1.1.1.origin.asn.cymru.com  → "13335 | 1.1.1.0/24 | AU | apnic | 2011-08-11"
    AS13335.asn.cymru.com         → "13335 | US | arin | 2010-07-14 | CLOUDFLARENET - …"

IPv6 uses nibble-reversed names under ``origin6.asn.cymru.com``. Private,
loopback and other non-global addresses are skipped. Results are cached
per process, so repeated routers (and repeated ASNs) cost nothing.

This sends each hop's IP address to Cymru's DNS servers (via your
resolver), which is why ``--asn`` is opt-in.
"""

from __future__ import annotations

import ipaddress
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from xping.diagnostics.lookup import query_txt


@dataclass(frozen=True)
class AsnInfo:
    asn: int
    name: str | None
    prefix: str | None
    country: str | None


_lock = threading.Lock()
_by_ip: dict[str, AsnInfo | None] = {}
_names: dict[int, str | None] = {}


def origin_name(ip: str) -> str | None:
    """The Cymru origin query name for *ip*, or None for non-global addresses."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return None
    if not addr.is_global:
        return None
    if addr.version == 4:
        return ".".join(reversed(str(addr).split("."))) + ".origin.asn.cymru.com"
    nibbles = addr.exploded.replace(":", "")
    return ".".join(reversed(nibbles)) + ".origin6.asn.cymru.com"


def _fields(record: str) -> list[str]:
    return [part.strip() for part in record.strip().strip('"').split("|")]


def parse_origin(records: list[str]) -> tuple[int, str | None, str | None] | None:
    """(asn, prefix, country) from origin TXT records, most specific prefix first."""
    best = None
    best_len = -1
    for record in records:
        parts = _fields(record)
        head = parts[0].split()
        if len(parts) < 2 or not head or not head[0].isdigit():
            continue
        asn = int(head[0])  # multi-origin prefixes list several ASNs
        prefix = parts[1] or None
        try:
            length = ipaddress.ip_network(prefix).prefixlen if prefix else 0
        except ValueError:
            length = 0
        if length > best_len:
            best_len = length
            best = (asn, prefix, parts[2] if len(parts) > 2 and parts[2] else None)
    return best


def parse_as_name(records: list[str]) -> str | None:
    for record in records:
        parts = _fields(record)
        if len(parts) >= 5 and parts[4]:
            return parts[4]
    return None


def _as_name(asn: int) -> str | None:
    with _lock:
        if asn in _names:
            return _names[asn]
    records, _err = query_txt(f"AS{asn}.asn.cymru.com")
    name = parse_as_name(records)
    with _lock:
        _names[asn] = name
    return name


def lookup(ip: str | None) -> AsnInfo | None:
    """ASN details for *ip* (cached), or None if unknown / not global."""
    if not ip:
        return None
    with _lock:
        if ip in _by_ip:
            return _by_ip[ip]
    info = None
    qname = origin_name(ip)
    if qname:
        records, _err = query_txt(qname)
        origin = parse_origin(records)
        if origin:
            asn, prefix, country = origin
            info = AsnInfo(asn=asn, name=_as_name(asn), prefix=prefix, country=country)
    with _lock:
        _by_ip[ip] = info
    return info


def annotate(hop) -> None:
    """Set ``hop.asn`` / ``hop.as_name`` in place (works for Hop and MtrHop)."""
    info = lookup(hop.ip)
    if info:
        hop.asn = info.asn
        hop.as_name = info.name


def annotate_all(hops: list, workers: int = 8) -> None:
    """Annotate many hops concurrently."""
    targets = [h for h in hops if h.ip]
    if not targets:
        return
    with ThreadPoolExecutor(max_workers=min(workers, len(targets))) as pool:
        list(pool.map(annotate, targets))
