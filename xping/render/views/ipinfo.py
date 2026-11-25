"""IP address information rendering (xping ip)."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_TEAL, BWHITE, DIM, c, safe
from ..tables import print_table

_SCOPE_WORDS = {
    "public": "public (reachable on the internet)",
    "private": "private (RFC 1918 / ULA, behind NAT)",
    "CGNAT": "carrier-grade NAT (100.64.0.0/10, shared by your ISP's customers)",
    "loopback": "loopback (this machine)",
    "link-local": "link-local (this network segment only)",
    "multicast": "multicast",
    "documentation": "documentation (never used on the internet)",
    "unspecified": "unspecified",
    "reserved": "reserved",
}


def _blocklist_text(result) -> str:
    if result.blocklist_listed:
        return c("LISTED on " + ", ".join(result.blocklist_listed), BRAND_ROSE, BOLD)
    if result.blocklist_error and not result.blocklist_checked:
        return c(safe(result.blocklist_error, keep_colors=False), BRAND_AMBER)
    text = c(f"clean ({result.blocklist_checked} lists)", BRAND_MINT, BOLD)
    if result.blocklist_policy:
        text += c(
            f"  · {', '.join(result.blocklist_policy)}: end-user range (fine unless it sends mail)",
            DIM,
        )
    return text


def print_result(result, blocklist: bool = True) -> None:
    print()
    if result.error:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
        print()
        return
    rows = [
        ["Address", c(result.ip, BRAND_TEAL, BOLD) + c(f"  IPv{result.version}", DIM)],
        ["Kind", _SCOPE_WORDS.get(result.scope, result.scope)],
    ]
    if result.ptr:
        check = (
            c("  ✔ points back", BRAND_MINT)
            if result.fcrdns
            else c("  ✘ does not point back", BRAND_AMBER)
        )
        rows.append(["Reverse DNS", c(safe(result.ptr, keep_colors=False), BWHITE) + check])
    else:
        rows.append(["Reverse DNS", c("none (no PTR record)", DIM)])
    if result.public:
        if result.asn is not None:
            operator = safe(result.as_name or "unknown", keep_colors=False)
            rows.append(["Network", c(f"AS{result.asn}", BWHITE, BOLD) + f"  {operator}"])
            if result.prefix:
                rows.append(["Prefix", safe(result.prefix, keep_colors=False)])
            if result.country:
                rows.append(["Country", safe(result.country, keep_colors=False)])
        else:
            rows.append(["Network", c("unknown (no answer from Team Cymru)", DIM)])
        if blocklist:
            rows.append(["Blocklists", _blocklist_text(result)])
    print_table(["Field", "Value"], rows)
    if result.ptr and result.fcrdns is False:
        print(c("  A mail server needs a PTR name that resolves back to its address.", DIM))
    if result.scope == "CGNAT":
        print(c("  Behind CGNAT, others cannot connect to you without a VPN or tunnel.", DIM))
    print()
