"""
xping.diagnostics.dnscheck — DNS health check.
Checks A/AAAA, NS redundancy, MX backup, SPF, DMARC, DKIM.
"""

import sys

from xping.diagnostics.lookup import lookup
from xping.models.dnscheck import DnsCheckItem, DnsCheckResult
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.views import dnscheck as dnscheck_view


def _ok(name: str, detail: str = "") -> DnsCheckItem:
    return DnsCheckItem(name=name, status="ok", detail=detail)


def _warn(name: str, detail: str = "") -> DnsCheckItem:
    return DnsCheckItem(name=name, status="warn", detail=detail)


def _fail(name: str, detail: str = "") -> DnsCheckItem:
    return DnsCheckItem(name=name, status="fail", detail=detail)


def _info(name: str, detail: str = "") -> DnsCheckItem:
    return DnsCheckItem(name=name, status="info", detail=detail)


def dnscheck(domain: str, quiet: bool = False) -> DnsCheckResult:
    domain = domain.strip().lower().rstrip(".")
    result = DnsCheckResult(domain=domain)

    if not quiet:
        print(section_header(f"DNS HEALTH CHECK  {domain}", "◎"))
        print(kv("Domain", c(domain, BRAND_TEAL, BOLD)))
        print()

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Running DNS checks…", BRAND_TEAL))
        spinner.start()

    dns = lookup(host=domain, full=True, quiet=True)

    if spinner:
        spinner.stop()

    checks: list[DnsCheckItem] = []

    # A / AAAA
    if dns.ipv4:
        result.ip = dns.ipv4[0]
        extra = f" (+{len(dns.ipv4) - 1} more)" if len(dns.ipv4) > 1 else ""
        checks.append(_ok("A record", f"{dns.ipv4[0]}{extra}"))
    else:
        checks.append(_fail("A record", "No IPv4 address found"))

    if dns.ipv6:
        checks.append(_ok("AAAA record", dns.ipv6[0][:40]))
    else:
        checks.append(_info("AAAA record", "No IPv6 — not required but recommended"))

    # NS redundancy
    if len(dns.ns) >= 2:
        checks.append(_ok("NS redundancy", f"{len(dns.ns)} nameservers"))
    elif len(dns.ns) == 1:
        checks.append(_warn("NS redundancy", "Only 1 nameserver — single point of failure"))
    else:
        checks.append(_fail("NS records", "No nameservers found"))

    # MX
    if len(dns.mx) >= 2:
        checks.append(_ok("MX records", f"{len(dns.mx)} mail servers"))
    elif len(dns.mx) == 1:
        checks.append(_warn("MX records", f"1 mail server ({dns.mx[0][1]}) — no backup MX"))
    else:
        checks.append(_info("MX records", "No mail servers (fine for non-email domains)"))

    # SPF
    spf = [t for t in dns.txt if t.startswith("v=spf")]
    if len(spf) == 1:
        if "-all" in spf[0]:
            checks.append(_ok("SPF", "Strict policy (-all)"))
        elif "~all" in spf[0]:
            checks.append(_warn("SPF", "Softfail (~all) — consider upgrading to -all"))
        elif "+all" in spf[0]:
            checks.append(_fail("SPF", "+all allows anyone to send — very dangerous"))
        else:
            checks.append(_ok("SPF", spf[0][:60]))
    elif len(spf) > 1:
        checks.append(_fail("SPF", f"{len(spf)} SPF records found — must be exactly 1"))
    else:
        checks.append(_fail("SPF", "No SPF record — emails may be rejected as spam"))

    # DMARC
    dmarc = [t for t in dns.txt if "v=dmarc1" in t.lower()]
    if dmarc:
        d = dmarc[0].lower()
        if "p=reject" in d:
            checks.append(_ok("DMARC", "Policy: reject (strongest)"))
        elif "p=quarantine" in d:
            checks.append(_warn("DMARC", "Policy: quarantine — consider p=reject"))
        elif "p=none" in d:
            checks.append(_warn("DMARC", "Policy: none (monitoring only)"))
        else:
            checks.append(_ok("DMARC", dmarc[0][:60]))
    else:
        checks.append(_fail("DMARC", "No DMARC record — no email authentication policy"))

    # DKIM (heuristic from TXT)
    dkim = [t for t in dns.txt if "v=dkim1" in t.lower() or ("k=rsa" in t.lower())]
    if dkim:
        checks.append(_ok("DKIM", "DKIM key found in TXT records"))
    else:
        checks.append(
            _info("DKIM", f"Cannot verify without selector — check <selector>._domainkey.{domain}")
        )

    result.checks = checks

    # Score
    scored = [c for c in checks if c.status != "info"]
    if scored:
        weights = {"ok": 10, "warn": 5, "fail": 0}
        total = sum(weights[c.status] for c in scored)
        result.score = round(total / (len(scored) * 10) * 100)
    else:
        result.score = 100

    if not quiet:
        dnscheck_view.print_result(result)
    return result
