"""ANSI escape helpers — all terminal colour codes live here."""

import os
import re
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


ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_len(text: str) -> int:
    """Length of *text* as shown on screen (colour codes take no space)."""
    return len(ANSI_RE.sub("", text))


def pad(text: str, width: int, align: str = "<") -> str:
    """Pad *text* to *width* visible columns. f-string padding counts the
    invisible colour codes, which misaligns columns — and differently with
    colour on and off — so padding of coloured text must go through here."""
    gap = max(0, width - visible_len(text))
    if align == ">":
        return " " * gap + text
    if align == "^":
        return " " * (gap // 2) + text + " " * (gap - gap // 2)
    return text + " " * gap


# Any terminal escape sequence: CSI (cursor moves, erase, …), OSC (title,
# clipboard, hyperlinks), DCS/SOS/PM/APC strings, and two-byte escapes.
_ANY_ESCAPE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[PX^_][^\x1b]*(?:\x1b\\)?|[@-Z\\-_])"
)
# C0 controls except tab/newline (so no \r or \b overwriting), DEL, and C1
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def safe(text: str, keep_colors: bool = True) -> str:
    """Make text from the network safe to print.

    Servers control much of what xping shows (HTTP headers, SMTP banners,
    WHOIS, DNS TXT/PTR, Wi-Fi names). An escape sequence in there could
    move the cursor and overwrite earlier lines, change the window title,
    or write to the clipboard (OSC 52). Only xping's own colour codes are
    kept; every other escape sequence is removed and every other control
    character becomes "?"."""
    out, pos = [], 0
    for m in _ANY_ESCAPE.finditer(text):
        out.append(_CONTROL.sub("?", text[pos : m.start()]))
        if keep_colors and COLOR and m.group() in _OWN_SGR:
            out.append(m.group())
        pos = m.end()
    out.append(_CONTROL.sub("?", text[pos:]))
    return "".join(out)


def c(text: str, *codes: str) -> str:
    """Wrap *text* with ANSI codes, stripping them when colour is off.
    *text* is passed through safe() — it may come from a remote server."""
    text = safe(str(text))
    if not COLOR:
        return text
    return "".join(codes) + text + RESET


# xping's own colour codes: the only escape sequences safe() lets through.
# Black foreground/background are left out (unused, and a way to hide text).
_OWN_SGR = frozenset(
    value
    for name, value in dict(globals()).items()
    if name.isupper()
    and isinstance(value, str)
    and value.startswith(ESC)
    and value.endswith("m")
    and name not in ("BLACK", "BG_BLACK", "ESC")
)
