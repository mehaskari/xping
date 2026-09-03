"""Saved profile rendering."""

from ..ansi import BOLD, BRAND_MINT, BRAND_TEAL, BWHITE, DIM, c
from ..layout import kv
from ..tables import print_table


def print_saved(entry) -> None:
    print(kv("Name", c(entry.name, BRAND_TEAL, BOLD)))
    print(kv("Target", c(entry.target, BWHITE)))
    if entry.port:
        print(kv("Port", str(entry.port)))
    if entry.note:
        print(kv("Note", entry.note))
    print()
    print(c("  ✔  Use it anywhere a host is expected: ", BRAND_MINT) +
          c(f"xping ping {entry.name}", BWHITE, BOLD))
    print()


def print_removed(name: str) -> None:
    print(c(f"\n  ✔  Removed profile '{name}'", BRAND_MINT, BOLD))
    print()


def print_entry(entry) -> None:
    print(kv("Name", c(entry.name, BRAND_TEAL, BOLD)))
    print(kv("Target", entry.target))
    print(kv("Port", str(entry.port) if entry.port else "—"))
    print(kv("Note", entry.note or "—"))
    print()


def print_list(result) -> None:
    if not result.profiles:
        print(c("  No profiles saved yet.", DIM))
        print(c("  Add one with: ", DIM) +
              c("xping profile add <name> <target>", BWHITE, BOLD))
        print()
        return

    rows = [
        [p.name, p.target, str(p.port) if p.port else "—", p.note or "—"]
        for p in result.profiles
    ]
    print_table(["Name", "Target", "Port", "Note"], rows)
    print()
