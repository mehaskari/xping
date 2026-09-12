"""Reverse DNS result rendering."""

from ..ansi import BOLD, BRAND_MINT, BWHITE, c
from ..errors import error
from ..tables import print_table


def print_result(result) -> None:
    badge = c(" ✔ PTR FOUND ", BRAND_MINT, BOLD)
    print(f"  {badge}  {c(result.hostname, BWHITE, BOLD)}")
    print()

    rows = [["IP", result.ip], ["Hostname", result.hostname]]
    if result.aliases:
        rows.append(["Aliases", ", ".join(result.aliases)])
    if result.addresses:
        rows.append(["Addresses", ", ".join(result.addresses)])
    print_table(["Field", "Value"], rows)
    print()


def print_error(result) -> None:
    error(result.error or "Reverse DNS lookup failed",
          hint="Not every IP has a PTR record — this is common and not a fault.")
