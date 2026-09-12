"""Progress line rendering."""

import sys
import time

from .ansi import BRAND_MINT, BRAND_TEAL, c


def progress_line(msg: str, done: bool = False) -> None:
    """Overwrite the current line with a progress indicator."""
    spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    sym = (
        c("✔", BRAND_MINT)
        if done
        else c(spinner[int(time.time() * 8) % len(spinner)], BRAND_TEAL)
    )
    line = f"\r  {sym}  {msg}  "
    sys.stdout.write(line)
    sys.stdout.flush()
    if done:
        sys.stdout.write("\n")


def clear_lines(n: int) -> None:
    """Move the cursor up *n* lines and clear each, for live-redrawn tables."""
    if n <= 0:
        return
    for _ in range(n):
        sys.stdout.write("\033[1A\033[2K")
    sys.stdout.flush()
