"""
xping.diagnostics.dnscheck — DNS health check.
Checks A/AAAA, NS redundancy, MX backup, SPF, DMARC, DKIM.
"""

import sys
from concurrent.futures import ThreadPoolExecutor

from xping.diagnostics.lookup import lookup, query_txt
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


def _unknown(name: str, status: str) -> DnsCheckItem:
    return DnsCheckItem(
        name=name, status="unknown", detail=f"DNS query failed ({status}) — could not verify"
    )


# Selectors used by the most common mail providers/tools. DKIM keys live at
# <selector>._domainkey.<domain> and selectors can't be enumerated, so this
# is best-effort: not finding one is informational, not a failure.
_DKIM_SELECTORS = (
    "default",
    "google",
    "selector1",
    "selector2",
    "k1",
    "k2",
    "dkim",
    "mail",
    "s1",
    "s2",
)


def _is_dkim_key(record: str) -> bool:
    low = record.strip().lower()
    return "v=dkim1" in low or low.startswith(("k=", "p="))


def _dmarc_policy(record: str) -> str | None:
    """Return the value of the DMARC `p=` tag (e.g. "reject")."""
    for tag in record.split(";"):
        key, _, value = tag.partition("=")
        if key.strip().lower() == "p":
            return value.strip().lower()
    return None


def _find_dkim(domain: str) -> tuple[str | None, str | None]:
    """Return (selector, None) for the first selector with a DKIM key, else
    (None, error) where error is set only if every probe failed outright."""
    names = [f"{sel}._domainkey.{domain}" for sel in _DKIM_SELECTORS]
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        answers = list(pool.map(query_txt, names))
    errors = []
    for selector, (records, err) in zip(_DKIM_SELECTORS, answers, strict=True):
        if any(_is_dkim_key(t) for t in records):
            return selector, None
        if err:
            errors.append(err)
    if len(errors) == len(names):
        return None, errors[0]
    return None, None


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
    dmarc_records, dmarc_err = query_txt(f"_dmarc.{domain}")
    dkim_selector, dkim_err = _find_dkim(domain)

    if spinner:
        spinner.stop()

    failed = dns.query_errors
    checks: list[DnsCheckItem] = []

    # A / AAAA
    if dns.ipv4:
        result.ip = dns.ipv4[0]
        extra = f" (+{len(dns.ipv4) - 1} more)" if len(dns.ipv4) > 1 else ""
        checks.append(_ok("A record", f"{dns.ipv4[0]}{extra}"))
    elif "A" in failed:
        checks.append(_unknown("A record", failed["A"]))
    else:
        checks.append(_fail("A record", "No IPv4 address found"))

    if dns.ipv6:
        checks.append(_ok("AAAA record", dns.ipv6[0][:40]))
    elif "AAAA" in failed:
        checks.append(_unknown("AAAA record", failed["AAAA"]))
    else:
        checks.append(_info("AAAA record", "No IPv6 — not required but recommended"))

    # NS redundancy
    if len(dns.ns) >= 2:
        checks.append(_ok("NS redundancy", f"{len(dns.ns)} nameservers"))
    elif len(dns.ns) == 1:
        checks.append(_warn("NS redundancy", "Only 1 nameserver — single point of failure"))
    elif "NS" in failed:
        checks.append(_unknown("NS records", failed["NS"]))
    else:
        checks.append(_fail("NS records", "No nameservers found"))

    # MX
    if len(dns.mx) >= 2:
        checks.append(_ok("MX records", f"{len(dns.mx)} mail servers"))
    elif len(dns.mx) == 1:
        checks.append(_warn("MX records", f"1 mail server ({dns.mx[0][1]}) — no backup MX"))
    elif "MX" in failed:
        checks.append(_unknown("MX records", failed["MX"]))
    else:
        checks.append(_info("MX records", "No mail servers (fine for non-email domains)"))

    # SPF
    spf = [t for t in dns.txt if t.lower().startswith("v=spf1")]
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
    elif "TXT" in failed:
        checks.append(_unknown("SPF", failed["TXT"]))
    else:
        checks.append(_fail("SPF", "No SPF record — emails may be rejected as spam"))

    # DMARC — published as TXT at _dmarc.<domain>, not at the apex
    dmarc = [t for t in dmarc_records if t.lower().startswith("v=dmarc1")]
    if dmarc:
        policy = _dmarc_policy(dmarc[0])
        if policy == "reject":
            checks.append(_ok("DMARC", "Policy: reject (strongest)"))
        elif policy == "quarantine":
            checks.append(_warn("DMARC", "Policy: quarantine — consider p=reject"))
        elif policy == "none":
            checks.append(_warn("DMARC", "Policy: none (monitoring only)"))
        else:
            checks.append(_ok("DMARC", dmarc[0][:60]))
    elif dmarc_err:
        checks.append(_unknown("DMARC", dmarc_err))
    else:
        checks.append(_fail("DMARC", f"No DMARC record at _dmarc.{domain}"))

    # DKIM — best-effort probe of common selectors
    if dkim_selector:
        checks.append(_ok("DKIM", f"Key found at {dkim_selector}._domainkey.{domain}"))
    elif dkim_err:
        checks.append(_unknown("DKIM", dkim_err))
    else:
        checks.append(
            _info(
                "DKIM",
                f"No key at common selectors — check <selector>._domainkey.{domain}",
            )
        )

    result.checks = checks

    # Score
    scored = [c for c in checks if c.status not in ("info", "unknown")]
    if scored:
        weights = {"ok": 10, "warn": 5, "fail": 0}
        total = sum(weights[c.status] for c in scored)
        result.score = round(total / (len(scored) * 10) * 100)
    else:
        result.score = 100

    if not quiet:
        dnscheck_view.print_result(result)
    return result
