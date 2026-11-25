"""
xping.diagnostics.ipinfo — everything about one IP address in one view.

``xping ip [ADDRESS|HOST]``: what kind of address it is, its reverse DNS
name (and whether that name points back), the network that announces it
(ASN, operator, prefix, country via Team Cymru's DNS), and whether it is on
a spam blocklist. Without an argument it describes your public address.
The lookups run in parallel and reuse the modules behind ``rdns``,
``trace --asn`` and ``blocklist``.
"""

from __future__ import annotations

import ipaddress
import socket
import sys
from concurrent.futures import ThreadPoolExecutor

from xping.diagnostics import asn as asn_diag
from xping.diagnostics import blocklist as blocklist_diag
from xping.diagnostics import net as net_diag
from xping.diagnostics import rdns as rdns_diag
from xping.diagnostics.resolve import ip_version, resolve
from xping.models.ipinfo import IpInfoResult
from xping.render import BRAND_TEAL, c, section_header
from xping.render.animations import Spinner
from xping.render.views import ipinfo as ipinfo_view

_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_DOCUMENTATION = tuple(
    ipaddress.ip_network(n)
    for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)


def scope(ip: str) -> str:
    """What kind of address *ip* is, in words."""
    addr = ipaddress.ip_address(ip.split("%", 1)[0])
    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local:
        return "link-local"
    if addr.is_multicast:
        return "multicast"
    if addr.is_unspecified:
        return "unspecified"
    if addr.version == 4 and addr in _CGNAT:
        return "CGNAT"
    if any(addr in net for net in _DOCUMENTATION if net.version == addr.version):
        return "documentation"
    if addr.is_global:
        return "public"
    if addr.is_reserved:
        return "reserved"
    if addr.is_private:
        return "private"
    return "reserved"


def forward_confirmed(name: str, ip: str) -> bool:
    """Does *name* resolve back to *ip*? (forward-confirmed reverse DNS)"""
    try:
        infos = socket.getaddrinfo(name, None)
    except (OSError, UnicodeError):
        return False
    want = ipaddress.ip_address(ip.split("%", 1)[0])
    return any(ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) == want for info in infos)


def _own_address(family: int | None) -> str | None:
    url = net_diag._TRACE_V6 if family == socket.AF_INET6 else net_diag._TRACE_V4
    found = net_diag._cf_trace(url).get("ip")
    if found is None and family is None:  # an IPv6-only network
        found = net_diag._cf_trace(net_diag._TRACE_V6).get("ip")
    return found


def _ptr(result: IpInfoResult, ip: str) -> None:
    found = rdns_diag.rdns(ip, quiet=True)
    if found.hostname:
        result.ptr = found.hostname.rstrip(".")
        result.fcrdns = forward_confirmed(result.ptr, ip)


def _asn(result: IpInfoResult, ip: str) -> None:
    info = asn_diag.lookup(ip)
    if info:
        result.asn, result.as_name = info.asn, info.name
        result.prefix, result.country = info.prefix, info.country


def _blocklist(result: IpInfoResult, ip: str) -> None:
    found = blocklist_diag.blocklist(ip, quiet=True)
    by_status: dict[str, list[str]] = {}
    for check in found.checks:
        by_status.setdefault(check.status, []).append(check.list_name)
    result.blocklist_listed = by_status.get(blocklist_diag.LISTED, [])
    result.blocklist_policy = by_status.get(blocklist_diag.POLICY, [])
    result.blocklist_checked = found.answered
    result.blocklist_error = found.error


def ipinfo(
    target: str | None = None,
    family: int | None = None,
    blocklist: bool = True,
    quiet: bool = False,
) -> IpInfoResult:
    """Describe *target* (an address or host name), or your public address."""
    result = IpInfoResult(query=(target or "").strip())
    title = result.query or "your public address"
    if not quiet:
        print(section_header(f"IP INFO  {title}", "◉"))

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Looking up the address…", BRAND_TEAL))
        spinner.start()
    try:
        if not result.query:
            result.ip = _own_address(family)
            if result.ip is None:
                result.error = "cannot find your public address (offline, or Cloudflare blocked?)"
        else:
            try:
                result.ip = resolve(result.query, family)
            except (socket.gaierror, UnicodeError):
                result.error = f"cannot resolve '{result.query}'"
        if result.ip:
            result.version = ip_version(result.ip)
            result.scope = scope(result.ip)
            jobs = [_ptr]
            if result.public:  # Cymru and the blocklists only know global space
                jobs.append(_asn)
                if blocklist:
                    jobs.append(_blocklist)
            with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
                for future in [pool.submit(job, result, result.ip) for job in jobs]:
                    future.result()
    finally:
        if spinner:
            spinner.stop()

    if not quiet:
        ipinfo_view.print_result(result, blocklist=blocklist)
    return result
