"""
xping.diagnostics.whois — WHOIS / RDAP domain lookup.
Primary path: raw TCP on port 43 (IANA → registry → registrar).
Fallback: RDAP over HTTPS when port 43 is blocked/firewalled.
Pure stdlib — no external libraries.
"""

import json
import re
import socket
import sys
import time
import urllib.request

from xping.diagnostics.sslctx import secure_context
from xping.models.whois import WhoisResult
from xping.render import BOLD, BRAND_TEAL, c, kv, section_header
from xping.render.animations import Spinner
from xping.render.errors import error
from xping.render.views import whois as whois_view

WHOIS_PORT = 43
IANA_SERVER = "whois.iana.org"
RDAP_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
WHOIS_TIMEOUT = 3.0  # per-attempt timeout for port-43
MAX_REFERRALS = 2
PORT43_RETRIES = 2  # 2 × 3s + 1 × 0.5s = 6.5s max before RDAP fallback
RDAP_RETRIES = 3
RETRY_DELAY = 0.5  # seconds between retries

_FIELD_PATTERNS: dict[str, list[str]] = {
    "registrar": [r"registrar:\s*(.+)", r"sponsoring registrar:\s*(.+)"],
    "creation_date": [
        r"creation date:\s*(.+)",
        r"created:\s*(.+)",
        r"domain registration date:\s*(.+)",
        r"registered on:\s*(.+)",
    ],
    "expiration_date": [
        r"registry expiry date:\s*(.+)",
        r"expiration date:\s*(.+)",
        r"expiry date:\s*(.+)",
        r"paid-till:\s*(.+)",
        r"registrar registration expiration date:\s*(.+)",
    ],
    "updated_date": [
        r"updated date:\s*(.+)",
        r"last modified:\s*(.+)",
        r"last updated:\s*(.+)",
    ],
}

# Hardcoded RDAP servers for common TLDs — avoids slow IANA bootstrap lookup
_RDAP_KNOWN: dict[str, str] = {
    "com": "https://rdap.verisign.com/com/v1",
    "net": "https://rdap.verisign.com/net/v1",
    "org": "https://rdap.publicinterestregistry.org/rdap",
    "io": "https://rdap.nic.io",
    "co": "https://rdap.nic.co",
    "app": "https://rdap.nic.google",
    "dev": "https://rdap.nic.google",
    "info": "https://rdap.afilias.net/rdap/info",
    "biz": "https://rdap.nic.biz",
    "me": "https://rdap.nic.me",
    "us": "https://rdap.nic.us",
    "uk": "https://rdap.nominet.uk",
    "de": "https://rdap.denic.de",
    "fr": "https://rdap.afnic.fr",
    "nl": "https://rdap.sidn.nl",
    "au": "https://rdap.auda.org.au",
    "ca": "https://rdap.cira.ca",
    # .ir intentionally omitted — nic.ir does not support RDAP
}


# ── Port-43 WHOIS ─────────────────────────────────────────────────────────────


def _query(server: str, query: str, timeout: float = WHOIS_TIMEOUT) -> str:
    """Raw WHOIS TCP query, forced IPv4, with retries for flaky connections."""
    try:
        infos = socket.getaddrinfo(server, WHOIS_PORT, socket.AF_INET, socket.SOCK_STREAM)
        ip, port = infos[0][4][0], infos[0][4][1]
    except socket.gaierror:
        ip, port = server, WHOIS_PORT

    last_exc: Exception = OSError("no attempts made")
    for attempt in range(PORT43_RETRIES):
        if attempt:
            time.sleep(RETRY_DELAY)
        try:
            with socket.create_connection((ip, port), timeout=timeout) as sock:
                sock.sendall((query + "\r\n").encode("ascii", errors="ignore"))
                chunks = []
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
        except (socket.timeout, TimeoutError, OSError) as exc:
            last_exc = exc
    raise last_exc


def _find_referral(text: str) -> str | None:
    m = re.search(
        r"(?:whois server|refer|referralserver):\s*(?:whois://)?(\S+)", text, re.IGNORECASE
    )
    return m.group(1).strip().rstrip("/") if m else None


def _parse(text: str) -> dict:
    fields: dict = {"status": [], "name_servers": []}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%") or stripped.startswith("#"):
            continue
        low = stripped.lower()
        if low.startswith(("name server:", "nserver:")):
            ns = stripped.split(":", 1)[1].strip().lower().rstrip(".")
            if ns and ns not in fields["name_servers"]:
                fields["name_servers"].append(ns)
            continue
        if low.startswith(("domain status:", "status:")):
            status = stripped.split(":", 1)[1].strip()
            status = status.split()[0] if status else status
            if status and status not in fields["status"]:
                fields["status"].append(status)
            continue
        for key, patterns in _FIELD_PATTERNS.items():
            if key in fields:
                continue
            for pattern in patterns:
                m = re.match(pattern, stripped, re.IGNORECASE)
                if m:
                    fields[key] = m.group(1).strip()
                    break
    return fields


# ── RDAP fallback ─────────────────────────────────────────────────────────────


def _rdap_url_for(tld: str) -> str | None:
    """Return RDAP base URL for *tld* — hardcoded list first, then IANA bootstrap."""
    known = _RDAP_KNOWN.get(tld.lower())
    if known:
        return known
    try:
        with urllib.request.urlopen(RDAP_BOOTSTRAP, timeout=5) as resp:
            data = json.loads(resp.read())
        for entry in data.get("services", []):
            tlds, urls = entry
            if tld.lower() in [t.lower() for t in tlds]:
                return urls[0].rstrip("/")
    except Exception:
        return None  # bootstrap unreachable or malformed — caller reports "no RDAP"
    return None


def _rdap_query(domain: str, tld: str) -> WhoisResult | None:
    """Query RDAP over HTTPS. Returns a WhoisResult or None on failure."""
    base = _rdap_url_for(tld)
    if not base:
        return None
    url = f"{base}/domain/{domain}"
    headers = {
        "Accept": "application/rdap+json, application/json",
        "User-Agent": "curl/7.88.0",
    }
    data = None
    ctx = secure_context()
    for attempt in range(RDAP_RETRIES):
        if attempt:
            time.sleep(RETRY_DELAY)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                data = json.loads(resp.read())
            break
        except Exception:
            continue
    if data is None:
        return None

    result = WhoisResult(domain=domain, whois_server=f"RDAP: {base}")

    for entity in data.get("entities", []):
        if "registrar" in entity.get("roles", []):
            vcard = entity.get("vcardArray", [])
            if isinstance(vcard, list) and len(vcard) > 1:
                for prop in vcard[1]:
                    if prop[0] == "fn":
                        result.registrar = prop[3]

    result.creation_date = data.get("registration") or data.get("creationDate")
    result.expiration_date = data.get("expiration") or data.get("expirationDate")
    result.updated_date = data.get("lastChangedDate") or data.get("updatedDate")
    result.status = [s.split()[-1] for s in data.get("status", [])]
    result.name_servers = [
        ns["ldhName"].lower() for ns in data.get("nameservers", []) if "ldhName" in ns
    ]
    result.raw_text = json.dumps(data, indent=2)
    return result


# ── Main entry point ──────────────────────────────────────────────────────────


def whois(domain: str, quiet: bool = False) -> WhoisResult:
    """Look up WHOIS registration data for *domain* (port 43 with RDAP fallback)."""
    domain = domain.strip().lower().rstrip(".")
    result = WhoisResult(domain=domain)

    if not quiet:
        print(section_header(f"WHOIS  {domain}", "◔"))
        print(kv("Query", c(domain, BRAND_TEAL, BOLD)))
        print()

    tld = domain.rsplit(".", 1)[-1]
    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Querying WHOIS (port 43)…", BRAND_TEAL))
        spinner.start()

    port43_ok = False
    try:
        iana_text = _query(IANA_SERVER, tld)
        server = _find_referral(iana_text) or IANA_SERVER
        result.whois_server = server

        text = iana_text
        seen_servers = {IANA_SERVER}
        for _ in range(MAX_REFERRALS):
            if server in seen_servers and server != IANA_SERVER:
                break
            seen_servers.add(server)
            if spinner:
                spinner.stop()
                spinner = Spinner(c(f"Querying {server}…", BRAND_TEAL))
                spinner.start()
            text = _query(server, domain)
            next_server = _find_referral(text)
            if not next_server or next_server == server or next_server in seen_servers:
                break
            server = next_server
            result.whois_server = server

        result.raw_text = text.strip()
        fields = _parse(text)
        result.registrar = fields.get("registrar")
        result.creation_date = fields.get("creation_date")
        result.expiration_date = fields.get("expiration_date")
        result.updated_date = fields.get("updated_date")
        result.status = fields.get("status", [])
        result.name_servers = fields.get("name_servers", [])

        if (
            not result.raw_text
            or "no match" in result.raw_text.lower()[:200]
            or "not found" in result.raw_text.lower()[:200]
        ):
            result.error = f"No WHOIS record found for '{domain}'"

        port43_ok = result.error is None

    except OSError:
        # Timeouts, refusals, and unresolvable WHOIS servers (gaierror is an
        # OSError subclass) all mean port 43 is unusable here — try RDAP.
        port43_ok = False
    finally:
        if spinner:
            spinner.stop()
            spinner = None

    # ── RDAP fallback ─────────────────────────────────────────────────────────
    if not port43_ok and not result.error:
        if not quiet and sys.stdout.isatty():
            spinner = Spinner(c("Port 43 unavailable — trying RDAP…", BRAND_TEAL))
            spinner.start()
        rdap = _rdap_query(domain, tld)
        if spinner:
            spinner.stop()
        if rdap:
            result = rdap
        else:
            rdap_url = _rdap_url_for(tld)
            if rdap_url:
                hint = f"Try: curl {rdap_url}/domain/{domain}"
            else:
                hint = f"The .{tld} registry may not support RDAP. Try: whois {domain}"
            result.error = f"WHOIS port 43 is blocked and RDAP also failed. {hint}"

    if not quiet:
        if result.error:
            error(result.error)
        else:
            whois_view.print_result(result)
    return result
