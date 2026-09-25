"""DNS lookup result rendering."""

from ..ansi import (
    BMAGENTA,
    BOLD,
    BRAND_AMBER,
    BRAND_INDIGO,
    BRAND_MINT,
    BRAND_SLATE,
    BRAND_TEAL,
    BWHITE,
    DIM,
    c,
)
from ..layout import kv
from ..tables import print_table


def print_result(result, full: bool = False) -> None:
    if result.ipv4:
        print(c("  ╔═ IPv4 (A records) ", BRAND_TEAL, BOLD) + c("─" * 40, DIM))
        rows = []
        for ip in result.ipv4:
            rev = result.reverse.get(ip, "—")
            rows.append(
                [
                    c(ip, BRAND_MINT, BOLD),
                    c(rev, BRAND_SLATE),
                    c(str(result.ttl) + "s" if result.ttl else "—", DIM),
                ]
            )
        print_table(["IPv4 Address", "Reverse DNS", "TTL"], rows)
        print()

    if result.cname:
        print(c("  ╔═ CNAME ", BRAND_INDIGO, BOLD) + c("─" * 50, DIM))
        print(kv("Alias for", c(result.cname, BRAND_AMBER, BOLD)))
        print()

    if result.ipv6:
        print(c("  ╔═ IPv6 (AAAA records) ", BRAND_INDIGO, BOLD) + c("─" * 38, DIM))
        rows = [
            [c(ip, BMAGENTA, BOLD), c(result.reverse.get(ip, "—"), BRAND_SLATE)]
            for ip in result.ipv6
        ]
        print_table(["IPv6 Address", "Reverse DNS"], rows)
        print()

    if result.mx:
        print(c("  ╔═ Mail (MX records) ", BRAND_AMBER, BOLD) + c("─" * 39, DIM))
        rows = [[c(str(prio), BRAND_AMBER, BOLD), c(host, BWHITE)] for prio, host in result.mx]
        print_table(["Priority", "Mail Server"], rows)
        print()

    if result.ns:
        print(c("  ╔═ Name Servers (NS records) ", BRAND_MINT, BOLD) + c("─" * 30, DIM))
        rows = [[c(ns, BRAND_MINT)] for ns in result.ns]
        print_table(["Nameserver"], rows)
        print()

    if full and result.txt:
        print(c("  ╔═ TXT records ", DIM, BOLD) + c("─" * 44, DIM))
        for txt in result.txt:
            if txt.startswith("v=spf"):
                tag = c(" SPF ", BRAND_MINT, BOLD)
            elif "DMARC" in txt.upper() or "dmarc" in txt:
                tag = c(" DMARC ", BRAND_AMBER, BOLD)
            elif "v=DKIM" in txt:
                tag = c(" DKIM ", BRAND_INDIGO, BOLD)
            else:
                tag = c(" TXT ", DIM)
            print(f"  {tag}  {c(txt[:120], BRAND_SLATE)}")
        print()

    total = len(result.ipv4) + len(result.ipv6)
    badge = c(
        f" ✔ {total} address{'es' if total != 1 else ''} found ",
        BRAND_MINT,
        BOLD,
    )
    print(f"  {badge}  {c(result.host, BWHITE, BOLD)}")
    if result.mx:
        print(c(f"  ✉  {len(result.mx)} mail server(s) configured", BRAND_AMBER))
    if result.ns:
        print(c(f"  🌐  {len(result.ns)} name server(s) found", BRAND_MINT))
    errors = getattr(result, "query_errors", {})
    if errors:
        failed = ", ".join(f"{rtype} ({status})" for rtype, status in errors.items())
        print(c(f"  ⚠  Query failed, results may be incomplete: {failed}", BRAND_AMBER))
    print()
