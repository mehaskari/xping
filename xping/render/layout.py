"""Layout primitives: banner, headers, key-value rows."""

import shutil

from .ansi import (
    BMAGENTA, BOLD, BRAND_INDIGO, BRAND_SLATE, BRAND_TEAL,
    BRAND_ROSE, BWHITE, BGREEN, DIM, ITALIC, c,
)


def terminal_width() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def rule(char: str = "─", color: str = BRAND_TEAL) -> str:
    return c(char * terminal_width(), color)


def banner() -> str:
    logo_lines = [
        c("  ██╗  ██╗██████╗ ██╗███╗   ██╗ ██████╗ ", BRAND_TEAL, BOLD),
        c("  ╚██╗██╔╝██╔══██╗██║████╗  ██║██╔════╝ ", BRAND_TEAL, BOLD),
        c("   ╚███╔╝ ██████╔╝██║██╔██╗ ██║██║  ███╗", BRAND_INDIGO, BOLD),
        c("   ██╔██╗ ██╔═══╝ ██║██║╚██╗██║██║   ██║", BRAND_INDIGO, BOLD),
        c("  ██╔╝ ██╗██║     ██║██║ ╚████║╚██████╔╝", BMAGENTA, BOLD),
        c("  ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═══╝ ╚═════╝ ", BMAGENTA, BOLD),
    ]
    from .. import __version__, __author__, __email__
    tagline = c("  network diagnostics  ·  beautiful by default", BRAND_SLATE, ITALIC)
    ver = c(f"v{__version__}", DIM)
    author = c(f"by {__author__}", BRAND_SLATE) + c(f" <{__email__}>", DIM)
    return "\n".join(logo_lines) + "\n" + tagline + "   " + ver + "\n  " + author + "\n"


def section_header(title: str, icon: str = "◈") -> str:
    w = terminal_width()
    left = c(f" {icon} ", BRAND_TEAL, BOLD)
    text = c(title.upper(), BWHITE, BOLD)
    pad = w - len(icon) + 1 - len(title) - 4
    line = c("─" * max(pad, 2), DIM)
    return f"\n{left}{text}  {line}"


def kv(label: str, value: str, label_w: int = 18) -> str:
    lbl = c(f"  {label:<{label_w}}", BRAND_SLATE)
    val = c(value, BWHITE)
    return f"{lbl}{val}"


def status_badge(ok: bool) -> str:
    if ok:
        return c(" ✔ ALIVE ", BGREEN, BOLD)
    return c(" ✘ UNREACHABLE ", BRAND_ROSE, BOLD)
