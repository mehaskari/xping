"""Connectivity doctor render view (xping doctor)."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c

_BADGES = {
    "ok": ("✔", BRAND_MINT),
    "info": ("ℹ", BRAND_SLATE),
    "skip": ("–", DIM),
    "warn": ("!", BRAND_AMBER),
    "fail": ("✘", BRAND_ROSE),
}


def print_step(step) -> None:
    icon, color = _BADGES.get(step.status, ("?", DIM))
    name_color = DIM if step.status == "skip" else BWHITE
    label = c(f"{step.name:<22}", name_color, BOLD if step.status == "fail" else "")
    detail = c(step.detail, DIM if step.status in ("skip", "info") else BWHITE)
    print(f"  {c(icon, color, BOLD)}  {label}  {detail}")
    # a failure's advice is printed once, with the diagnosis at the end
    if step.hint and step.status == "warn":
        print(c(f"     {'':<22}  → {step.hint}", color))


def print_diagnosis(result) -> None:
    print()
    if not result.ok:
        color, icon = BRAND_ROSE, "✘"
    elif result.warnings:
        color, icon = BRAND_AMBER, "!"
    else:
        color, icon = BRAND_MINT, "✔"
    print(c(f"  {icon} {result.diagnosis}", color, BOLD))
    if result.hint:
        print(c(f"    {result.hint}", BRAND_SLATE))
    print()
