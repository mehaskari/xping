"""DNS blocklist render view (xping blocklist)."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from ..layout import kv
from ..tables import print_table

_STATUS = {
    "listed": ("✘ LISTED", BRAND_ROSE),
    "policy": ("ℹ policy", BRAND_AMBER),
    "clean": ("✔ clean", BRAND_MINT),
    "refused": ("? refused", BRAND_SLATE),
    "error": ("? error", BRAND_SLATE),
}


def print_result(result) -> None:
    if result.kind == "domain":
        checked = ", ".join(result.addresses) or "—"
        print(kv("Mail/web IPs", c(checked, BWHITE)))
    if result.skipped:
        print(kv("Not checked", c(", ".join(result.skipped) + "  (IPv6)", DIM)))
    print()
    if result.checks:
        rows = []
        for check in result.checks:
            label, color = _STATUS[check.status]
            detail = check.reason or (", ".join(check.codes) if check.codes else "")
            rows.append(
                [
                    c(label, color, BOLD),
                    c(check.list_name, BWHITE),
                    c(check.subject, DIM),
                    c(detail, DIM if check.status != "listed" else BRAND_ROSE),
                ]
            )
        print_table(["Status", "List", "Checked", "Details"], rows)
        print()
    if result.error:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
    elif result.listed_count:
        print(
            c(f"  ✘ Listed on {result.listed_count} blocklist(s): ", BRAND_ROSE, BOLD)
            + c(", ".join(result.listed), BRAND_ROSE)
        )
        print(
            c("    Mail from a listed address is often rejected; each list's website", BRAND_SLATE)
        )
        print(c("    explains why it was listed and how to request removal.", BRAND_SLATE))
    else:
        print(
            c(
                f"  ✔ Not listed on any of the {result.answered} lists that answered",
                BRAND_MINT,
                BOLD,
            )
        )
    if any(ch.status == "policy" for ch in result.checks):
        print(
            c(
                "  ℹ Spamhaus PBL lists end-user address ranges — normal for home and mobile"
                " connections, a problem only for a mail server.",
                DIM,
            )
        )
    if any(ch.status == "refused" for ch in result.checks):
        print(
            c(
                "  ? Some lists refuse queries sent through public resolvers (8.8.8.8, 1.1.1.1);"
                " use your ISP's or your own resolver for them.",
                DIM,
            )
        )
    print()
