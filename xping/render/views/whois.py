"""WHOIS result rendering."""

from ..ansi import BOLD, BRAND_INDIGO, BRAND_MINT, BWHITE, DIM, c
from ..tables import print_table


def print_result(result) -> None:
    badge = c(" ✔ RECORD FOUND ", BRAND_MINT, BOLD)
    print(f"  {badge}  {c(result.domain, BWHITE, BOLD)}")
    print()

    rows = [
        ["WHOIS server", result.whois_server or "—"],
        ["Registrar", result.registrar or "—"],
        ["Created", result.creation_date or "—"],
        ["Expires", result.expiration_date or "—"],
        ["Updated", result.updated_date or "—"],
    ]
    if result.status:
        rows.append(["Status", ", ".join(result.status[:4])])
    if result.name_servers:
        rows.append(["Name servers", ", ".join(result.name_servers[:6])])
    print_table(["Field", "Value"], rows)
    print()

    print(c("  Tip: pass --json to capture the full raw WHOIS response.", DIM))
    print()
