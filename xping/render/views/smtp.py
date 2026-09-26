"""SMTP server render view (xping smtp)."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from ..latency import latency_color
from ..layout import kv

_WANTED = ("PIPELINING", "8BITMIME", "SMTPUTF8", "CHUNKING", "ENHANCEDSTATUSCODES")


def _yes(ok: bool, yes: str, no: str, bad=BRAND_ROSE) -> str:
    return c(yes, BRAND_MINT, BOLD) if ok else c(no, bad, BOLD)


def print_result(result) -> None:
    if result.ip and result.ip != result.server:
        print(kv("IP", c(result.ip, BWHITE)))
    if result.mx_hosts and result.server != result.host:
        print(kv("All MX", c(", ".join(result.mx_hosts), DIM)))
    if result.reverse_dns is not None or result.ip:
        if result.reverse_dns is None:
            ptr = c("none — many receivers distrust senders without reverse DNS", BRAND_AMBER)
        elif result.forward_confirmed:
            ptr = c(result.reverse_dns, BWHITE) + c("  ✔ resolves back", BRAND_MINT)
        else:
            ptr = c(result.reverse_dns, BWHITE) + c(
                "  ✘ does not resolve back to this IP", BRAND_AMBER
            )
        print(kv("Reverse DNS", ptr))
    print()
    if result.error and result.banner is None:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
        if result.port == 25 and "timed out" in result.error:
            print(
                c(
                    "    Many ISPs and clouds block outbound port 25; try --port 587 or 465.",
                    BRAND_SLATE,
                )
            )
        print()
        return

    if result.connect_ms is not None:
        print(kv("Connect", latency_color(result.connect_ms)))
    code_ok = result.banner_code == 220
    banner = f"{result.banner_code} {result.banner or ''}".strip()
    print(kv("Greeting", c(banner[:90], BWHITE if code_ok else BRAND_ROSE)))

    if result.implicit_tls:
        print(kv("TLS", _yes(result.tls, "implicit TLS (SMTPS)", "failed")))
    elif result.starttls_offered is not None:
        print(
            kv(
                "STARTTLS",
                _yes(result.starttls_offered, "offered", "NOT offered — mail travels unencrypted"),
            )
        )
    if result.tls:
        tls = f"{result.tls_version}  {result.tls_cipher or ''}".strip()
        print(kv("TLS version", c(tls, BWHITE)))
    if result.cert_error:
        print(kv("Certificate", c(f"✘ {result.cert_error}", BRAND_ROSE, BOLD)))
    elif result.cert_subject:
        days = result.cert_days
        color = (
            BRAND_MINT if days is None or days > 14 else BRAND_AMBER if days >= 0 else BRAND_ROSE
        )
        expiry = f"  expires in {days} days" if days is not None else ""
        print(kv("Certificate", c("✔ valid for this name", BRAND_MINT) + c(expiry, color)))
        print(kv("  Issuer", c(result.cert_issuer or "—", DIM)))

    if result.auth:
        print(kv("AUTH", c(" ".join(result.auth), BWHITE)))
    if result.max_size:
        print(kv("Max message", c(f"{result.max_size / 1_048_576:.0f} MB", BWHITE)))
    shown = [e for e in _WANTED if e in result.extensions]
    if shown:
        print(kv("Extensions", c(" ".join(shown), DIM)))
    print()

    if result.error:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
    elif not code_ok:
        print(c(f"  ✘ The server refused the session ({result.banner_code})", BRAND_ROSE, BOLD))
    elif result.cert_error:
        print(
            c("  ! The server answers, but its TLS certificate does not verify", BRAND_AMBER, BOLD)
        )
    elif result.starttls_offered is False:
        print(c("  ! The server answers, but offers no encryption", BRAND_AMBER, BOLD))
    else:
        print(c(f"  ✔ {result.server} accepts SMTP with valid TLS", BRAND_MINT, BOLD))
    print()
