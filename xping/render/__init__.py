"""
Terminal rendering utilities for xping.
Pure stdlib ANSI escape codes — no external dependencies.
"""

from .ansi import (
    BBLUE, BG_BLACK, BG_BLUE, BG_CARD, BG_CYAN, BG_DARK, BGREEN,
    BLACK, BMAGENTA, BOLD, BRED, BRAND_AMBER, BRAND_INDIGO, BRAND_MINT,
    BRAND_ROSE, BRAND_SLATE, BRAND_TEAL, BWHITE, BYELLOW, BCYAN,
    COLOR, CYAN, DIM, ESC, GREEN, ITALIC, MAGENTA, RED, RESET, WHITE,
    YELLOW, c, supports_color,
)
from .animations import Spinner
from .errors import error, missing_tool, resolve_error, warn
from .latency import latency_color, rtt_bar, spark_bar
from .layout import banner, kv, rule, section_header, status_badge, terminal_width
from .progress import clear_lines, progress_line
from .tables import print_table

__all__ = [
    "BBLUE", "BG_BLACK", "BG_BLUE", "BG_CARD", "BG_CYAN", "BG_DARK", "BGREEN",
    "BLACK", "BMAGENTA", "BOLD", "BRED", "BRAND_AMBER", "BRAND_INDIGO",
    "BRAND_MINT", "BRAND_ROSE", "BRAND_SLATE", "BRAND_TEAL", "BWHITE",
    "BYELLOW", "BCYAN", "COLOR", "CYAN", "DIM", "ESC", "GREEN", "ITALIC",
    "MAGENTA", "RED", "RESET", "WHITE", "YELLOW", "Spinner", "banner", "c",
    "clear_lines", "error", "kv", "latency_color", "missing_tool", "print_table", "progress_line",
    "resolve_error", "rule",
    "rtt_bar", "section_header", "spark_bar", "status_badge", "supports_color",
    "terminal_width", "warn",
]
