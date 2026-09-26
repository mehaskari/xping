"""
xping.diagnostics.blocklist — is an IP or domain on a spam blocklist?

DNS blocklists (DNSBL / RHSBL) are queried over plain DNS: to check
192.0.2.10 against zen.spamhaus.org, look up 10.2.0.192.zen.spamhaus.org.
An answer in 127.0.0.0/8 means "listed" (the last octet says why), and
NXDOMAIN means "not listed". A domain is looked up as
example.com.dbl.spamhaus.org.

For a domain, xping checks the domain on the domain lists and the IPv4
addresses of its mail servers (MX) and web host (A) on the IP lists —
which is what decides whether its mail gets delivered.

Queries go through the system resolver. Some lists (Spamhaus, URIBL)
refuse queries that arrive via big public resolvers such as 8.8.8.8 and
answer with special codes; those are reported as "refused", not listed.
"""

from __future__ import annotations

import ipaddress
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from xping.diagnostics.lookup import query
from xping.diagnostics.net import _read_resolv
from xping.models.blocklist import (
    CLEAN,
    ERROR,
    LISTED,
    POLICY,
    REFUSED,
    BlocklistCheck,
    BlocklistResult,
)
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.views import blocklist as blocklist_view

IP_LISTS: tuple[tuple[str, str], ...] = (
    ("Spamhaus ZEN", "zen.spamhaus.org"),
    ("SpamCop", "bl.spamcop.net"),
    ("Barracuda", "b.barracudacentral.org"),
    ("PSBL", "psbl.surriel.com"),
    ("Mailspike", "bl.mailspike.net"),
    ("UCEPROTECT L1", "dnsbl-1.uceprotect.net"),
    ("DroneBL", "dnsbl.dronebl.org"),
    ("s5h", "all.s5h.net"),
)
DOMAIN_LISTS: tuple[tuple[str, str], ...] = (
    ("Spamhaus DBL", "dbl.spamhaus.org"),
    ("SURBL", "multi.surbl.org"),
    ("URIBL", "multi.uribl.com"),
)
MAX_ADDRESSES = 6

_ZEN_CODES = {
    "127.0.0.2": "SBL (spam source)",
    "127.0.0.3": "SBL CSS (snowshoe spam)",
    "127.0.0.4": "XBL (exploited / infected host)",
    "127.0.0.5": "XBL (exploited / infected host)",
    "127.0.0.6": "XBL (exploited / infected host)",
    "127.0.0.7": "XBL (exploited / infected host)",
    "127.0.0.9": "SBL DROP (hijacked range)",
    "127.0.0.10": "PBL (end-user address range)",
    "127.0.0.11": "PBL (end-user address range)",
}
_PBL = {"127.0.0.10", "127.0.0.11"}


def reverse_ip(ip: str) -> str:
    return ".".join(reversed(ip.split(".")))


def classify(zone: str, codes: list[str]) -> tuple[str, str]:
    """(status, reason) for the A records a list returned."""
    if not codes:
        return CLEAN, ""
    if any(code.startswith("127.255.255.") for code in codes):
        return REFUSED, "the list refused the query (public resolver or rate limit)"
    if zone in ("multi.uribl.com", "multi.surbl.org") and codes == ["127.0.0.1"]:
        return REFUSED, "the list refused the query (public resolver)"
    if zone == "dbl.spamhaus.org" and "127.0.1.255" in codes:
        return REFUSED, "not a domain the list accepts"
    if not all(code.startswith("127.") for code in codes):
        return ERROR, "unexpected answer " + ", ".join(codes) + " (DNS hijacking?)"
    if zone == "zen.spamhaus.org":
        reasons = sorted({_ZEN_CODES.get(code, code) for code in codes})
        if set(codes) <= _PBL:
            return POLICY, "; ".join(reasons)
        return LISTED, "; ".join(r for r in reasons if not r.startswith("PBL"))
    return LISTED, ""


def lookup_a(name: str, timeout: float) -> tuple[list[str] | None, float]:
    """A records of *name* via the system resolver: a list (empty when the
    name does not exist), or None when the lookup timed out or failed."""
    started = time.perf_counter()
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(socket.gethostbyname_ex, name)
    try:
        codes = sorted(future.result(timeout=timeout)[2])
    except socket.herror:
        codes = []
    except socket.gaierror as exc:
        # NXDOMAIN is "not listed"; anything else is a lookup failure
        not_found = {getattr(socket, "EAI_NONAME", -2), getattr(socket, "EAI_NODATA", -5)}
        codes = [] if exc.errno in not_found else None
    except (FutureTimeout, OSError):
        codes = None
    finally:
        pool.shutdown(wait=False)
    return codes, (time.perf_counter() - started) * 1000


def check_one(list_name: str, zone: str, subject: str, timeout: float) -> BlocklistCheck:
    name = f"{reverse_ip(subject)}.{zone}" if _is_ipv4(subject) else f"{subject}.{zone}"
    codes, elapsed = lookup_a(name, timeout)
    if codes is None:
        return BlocklistCheck(
            list_name, zone, subject, ERROR, reason="lookup failed", elapsed_ms=elapsed
        )
    status, reason = classify(zone, codes)
    return BlocklistCheck(list_name, zone, subject, status, codes, reason, elapsed)


def _is_ipv4(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).version == 4
    except ValueError:
        return False


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def mail_and_web_addresses(domain: str) -> list[str]:
    """IPv4 and IPv6 addresses of the domain's MX hosts, then its A records."""
    hosts: list[str] = []
    status, mx, _ms = query(domain, "MX")
    if status == "ERROR":  # no dig: ask the configured nameserver directly
        servers = _read_resolv("/etc/resolv.conf")
        if servers:
            status, mx, _ms = query(domain, "MX", servers[0])
    for record in mx:  # "10 mx1.example.com"
        host = record.split()[-1]
        if host not in hosts:
            hosts.append(host)
    hosts.append(domain)
    addresses: list[str] = []
    for host in hosts:
        try:
            infos = socket.getaddrinfo(host, 25, 0, socket.SOCK_STREAM)
        except OSError:
            continue
        for info in infos:
            ip = info[4][0]
            if ip not in addresses:
                addresses.append(ip)
    return addresses


def blocklist(
    target: str,
    extra_zones: list[str] | None = None,
    timeout: float = 5.0,
    quiet: bool = False,
    show_all: bool = False,
) -> BlocklistResult:
    target = target.strip().rstrip(".").lower()
    kind = "ip" if _is_ip(target) else "domain"
    result = BlocklistResult(target=target, kind=kind)
    ip_lists = list(IP_LISTS) + [(zone, zone) for zone in extra_zones or []]

    if not quiet:
        print(section_header(f"BLOCKLIST CHECK  {target}", "⊘"))
        print(kv("Target", c(target, BRAND_TEAL, BOLD)))

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Querying blocklists…", BRAND_TEAL))
        spinner.start()
    try:
        jobs: list[tuple[str, str, str]] = []
        if kind == "ip":
            addresses = [target]
        else:
            jobs += [(name, zone, target) for name, zone in DOMAIN_LISTS]
            addresses = mail_and_web_addresses(target)
            if not addresses:
                result.error = f"cannot resolve '{target}' (no MX or A records)"
        for ip in addresses[:MAX_ADDRESSES]:
            if _is_ipv4(ip):
                result.addresses.append(ip)
                jobs += [(name, zone, ip) for name, zone in ip_lists]
            else:
                result.skipped.append(ip)  # few lists support IPv6
        with ThreadPoolExecutor(max_workers=16) as pool:
            result.checks = list(pool.map(lambda job: check_one(*job, timeout), jobs))
    finally:
        if spinner:
            spinner.stop()

    if not result.error and result.checks and not result.answered:
        result.error = "no blocklist answered (DNS blocked or offline?)"
    if not quiet:
        blocklist_view.print_result(result, show_all=show_all)
    return result
