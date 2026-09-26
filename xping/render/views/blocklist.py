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


def _detail_rows(checks) -> list[list[str]]:
    rows = []
    for check in checks:
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
    return rows


def _summary_rows(result) -> list[list[str]]:
    """One row per checked IP/domain: how many lists it is clean on, and
    which lists reported anything else."""
    subjects: dict[str, list] = {}
    for check in result.checks:
        subjects.setdefault(check.subject, []).append(check)
    rows = []
    for subject, checks in subjects.items():
        clean = sum(1 for ch in checks if ch.status == "clean")
        kind = "domain" if subject == result.target and result.kind == "domain" else "IP"
        problems = [ch for ch in checks if ch.status != "clean"]
        worst = next(
            (
                s
                for s in ("listed", "policy", "refused", "error")
                if any(ch.status == s for ch in problems)
            ),
            "clean",
        )
        label, color = _STATUS[worst]
        text = f"clean on {clean}/{len(checks)} {kind} lists"
        if problems:
            names = ", ".join(f"{ch.list_name} ({ch.status})" for ch in problems)
            text += f" · {names}"
        rows.append(
            [c(label, color, BOLD), c(subject, BWHITE), c(text, DIM if worst == "clean" else color)]
        )
    return rows


def print_result(result, show_all: bool = False) -> None:
    if result.kind == "domain":
        checked = ", ".join(result.addresses) or "—"
        print(kv("Mail/web IPs", c(checked, BWHITE)))
    if result.skipped:
        print(kv("Not checked", c(", ".join(result.skipped) + "  (IPv6)", DIM)))
    print()
    if result.checks:
        if show_all:
            print_table(["Status", "List", "Checked", "Details"], _detail_rows(result.checks))
        else:
            print_table(["Status", "Checked", "Result"], _summary_rows(result))
            problems = [ch for ch in result.checks if ch.status != "clean"]
            if problems:
                print()
                print(c("  Details:", BRAND_SLATE))
                print_table(["Status", "List", "Checked", "Details"], _detail_rows(problems))
        print()
    lists = len({ch.zone for ch in result.checks})
    scope = f"{len(result.checks)} checks on {lists} lists"
    if result.error:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
    elif result.listed_count:
        print(
            c(
                f"  ✘ Listed on {result.listed_count} of {scope}: ",
                BRAND_ROSE,
                BOLD,
            )
            + c(", ".join(result.listed), BRAND_ROSE)
        )
        print(
            c("    Mail from a listed address is often rejected; each list's website", BRAND_SLATE)
        )
        print(c("    explains why it was listed and how to request removal.", BRAND_SLATE))
    else:
        unanswered = len(result.checks) - result.answered
        note = f", {unanswered} unanswered" if unanswered else ", all answered"
        print(c(f"  ✔ Not listed — {scope}{note}", BRAND_MINT, BOLD))
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
