"""ANSI escape helpers — all terminal colour codes live here."""

import os
import sys

ESC = "\033["


def _c(*codes: int) -> str:
    return f"{ESC}{';'.join(map(str, codes))}m"


RESET = _c(0)
BOLD = _c(1)
DIM = _c(2)
ITALIC = _c(3)

BLACK = _c(30)
RED = _c(31)
GREEN = _c(32)
YELLOW = _c(33)
BLUE = _c(34)
MAGENTA = _c(35)
CYAN = _c(36)
WHITE = _c(37)

BRED = _c(91)
BGREEN = _c(92)
BYELLOW = _c(93)
BBLUE = _c(94)
BMAGENTA = _c(95)
BCYAN = _c(96)
BWHITE = _c(97)

BG_BLACK = _c(40)
BG_BLUE = _c(44)
BG_CYAN = _c(46)


def _rgb_fg(r: int, g: int, b: int) -> str:
    return f"{ESC}38;2;{r};{g};{b}m"


def _rgb_bg(r: int, g: int, b: int) -> str:
    return f"{ESC}48;2;{r};{g};{b}m"


BRAND_TEAL = _rgb_fg(0, 210, 190)
BRAND_INDIGO = _rgb_fg(100, 120, 255)
BRAND_AMBER = _rgb_fg(255, 190, 50)
BRAND_ROSE = _rgb_fg(255, 80, 110)
BRAND_MINT = _rgb_fg(130, 255, 190)
BRAND_SLATE = _rgb_fg(160, 170, 200)

BG_DARK = _rgb_bg(18, 20, 28)
BG_CARD = _rgb_bg(28, 32, 46)


def supports_color() -> bool:
    """Return True if the terminal supports ANSI colour codes."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return True


COLOR = supports_color()


def c(text: str, *codes: str) -> str:
    """Wrap *text* with ANSI codes, stripping them when colour is off."""
    if not COLOR:
        return text
    return "".join(codes) + text + RESET
