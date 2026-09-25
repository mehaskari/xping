"""Local network overview render view (xping net)."""

from ..ansi import BOLD, BRAND_INDIGO, BRAND_MINT, BRAND_ROSE, BRAND_TEAL, BWHITE, DIM, c
from ..layout import kv
from ..tables import print_table


def _val(value, color=BWHITE) -> str:
    return c(value, color) if value else c("—", DIM)


def _link_local_only(iface) -> bool:
    return all(a.lower().startswith(("fe80:", "169.254.")) for a in iface.addresses)


def _sorted(addresses: list[str]) -> list[str]:
    return sorted(addresses, key=lambda a: (":" in a, a.lower().startswith("fe80:")))


def print_result(result, public: bool = True, show_all: bool = False) -> None:
    print(kv("Hostname", _val(result.hostname, BRAND_TEAL)))
    print(kv("Local IPv4", _val(result.local_ipv4, BRAND_INDIGO)))
    print(kv("Local IPv6", _val(result.local_ipv6, BRAND_INDIGO)))
    gateway = result.gateway_ipv4
    if gateway and result.gateway_interface:
        gateway = f"{gateway}  via {result.gateway_interface}"
    print(kv("Gateway (IPv4)", _val(gateway)))
    print(kv("Gateway (IPv6)", _val(result.gateway_ipv6)))
    print(kv("DNS servers", _val(", ".join(result.dns_servers))))
    if public:
        where = ", ".join(p for p in (result.location, result.colo and f"via {result.colo}") if p)
        v4 = result.public_ipv4 + (f"  ({where})" if where else "") if result.public_ipv4 else None
        print(kv("Public IPv4", _val(v4, BRAND_MINT)))
        print(kv("Public IPv6", _val(result.public_ipv6, BRAND_MINT)))
        if not result.public_ipv6:
            print(c("  " + " " * 18 + "no IPv6 connectivity to the internet", DIM))
    print()

    candidates = [i for i in result.interfaces if i.addresses and not i.loopback]
    shown = [
        i
        for i in candidates
        if show_all or not _link_local_only(i) or i.name == result.gateway_interface
    ]
    hidden = len(candidates) - len(shown)
    if shown:
        rows = []
        for iface in shown:
            state = (
                c("up", BRAND_MINT, BOLD)
                if iface.state == "up"
                else c(iface.state, BRAND_ROSE if iface.state == "down" else DIM)
            )
            rows.append(
                [
                    c(iface.name, BWHITE, BOLD),
                    state,
                    str(iface.mtu) if iface.mtu else c("—", DIM),
                    _sorted(iface.addresses)[0],
                ]
            )
            for extra in _sorted(iface.addresses)[1:]:
                rows.append(["", "", "", extra])
        print_table(["Interface", "State", "MTU", "Addresses"], rows)
        print()
    if hidden:
        print(c(f"  {hidden} interface(s) with only link-local addresses hidden — use --all", DIM))
        print()
    if result.error:
        print(c(f"  {result.error}", BRAND_ROSE))
        print()
