"""Path MTU discovery result rendering."""

from ..ansi import BOLD, BRAND_MINT, BRAND_ROSE, BWHITE, DIM, c
from ..tables import print_table


def print_probe(size: int, ok: bool) -> None:
    badge = c("✔", BRAND_MINT) if ok else c("✘", BRAND_ROSE)
    print(c(f"  {badge}  probing {size}-byte payload…", DIM))


def print_summary(result) -> None:
    badge = c(" ✔ PATH MTU FOUND ", BRAND_MINT, BOLD)
    print()
    print(f"  {badge}  {c(f'{result.path_mtu} bytes', BWHITE, BOLD)}")
    print()

    rows = [
        ["Path MTU (IP packet)", f"{result.path_mtu} bytes"],
        ["Max ICMP payload", f"{result.max_payload} bytes"],
        ["Probes sent", str(len(result.probes))],
    ]
    print_table(["Metric", "Value"], rows)
    print()

    if result.path_mtu < 1500:
        print(
            c(
                f"  ℹ  Path MTU ({result.path_mtu}) is below the standard "
                "Ethernet MTU (1500) — a tunnel, VPN, or PPPoE link is "
                "likely fragmenting or dropping larger packets along the way.",
                DIM,
            )
        )
        print()
