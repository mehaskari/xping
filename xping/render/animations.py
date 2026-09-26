"""Animated terminal widgets."""

import re
import sys
import threading
import time

from .ansi import BOLD, BRAND_TEAL, c
from .layout import terminal_width

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_ANSI = re.compile(r"\033\[[0-9;]*m")


def fit(text: str, width: int) -> str:
    """Cut *text* to *width* visible characters, keeping its ANSI colour
    codes (and closing them), and ending with "…" when it was cut."""
    if width <= 0:
        return ""
    if len(_ANSI.sub("", text)) <= width:
        return text
    out, visible, pos = [], 0, 0
    for m in _ANSI.finditer(text):
        chunk = text[pos : m.start()]
        take = chunk[: max(0, width - 1 - visible)]
        out.append(take)
        visible += len(take)
        if visible >= width - 1:
            break
        out.append(m.group())
        pos = m.end()
    else:
        out.append(text[pos:][: max(0, width - 1 - visible)])
    return "".join(out) + "…" + ("\033[0m" if _ANSI.search(text) else "")


class Spinner:
    """Prints an animated spinner on the current line until stopped."""

    def __init__(self, prefix: str):
        self._prefix = prefix
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        i = 0
        while not self._stop.is_set():
            frame = c(SPINNER_FRAMES[i % len(SPINNER_FRAMES)], BRAND_TEAL, BOLD)
            # One line only: text that wraps can't be redrawn with "\r" and
            # would pile up on narrow terminals. 5 = "  ⠋  "; the last column
            # stays free because writing into it wraps on some terminals.
            prefix = fit(self._prefix, terminal_width() - 6)
            sys.stdout.write(f"\r  {frame}  {prefix}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join()
        sys.stdout.write("\r" + " " * (terminal_width() - 1) + "\r")
        sys.stdout.flush()
