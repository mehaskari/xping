"""Animated terminal widgets."""

import sys
import threading
import time

from .ansi import BOLD, BRAND_TEAL, c
from .layout import terminal_width

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


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
            sys.stdout.write(f"\r  {frame}  {self._prefix}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join()
        sys.stdout.write("\r" + " " * terminal_width() + "\r")
        sys.stdout.flush()
