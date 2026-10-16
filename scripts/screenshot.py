#!/usr/bin/env python3
"""
Render a real xping run as an SVG "terminal window" for the README.

  python3 scripts/screenshot.py docs/assets/doctor.svg -- doctor
  python3 scripts/screenshot.py docs/assets/ping.svg --cols 90 -- ping 1.1.1.1 -c 6

The command runs in a pseudo-terminal (so xping draws in colour, with its
live redraws), and a small terminal emulator replays the output: text,
carriage returns, line clearing, cursor up and the colours xping uses
(16 colours, bold, dim, 24-bit). Only what is left on screen at the end
is drawn, as an SVG with real text: sharp at any size, small, and
selectable on GitHub. macOS and Linux only (pty).
"""

from __future__ import annotations

import argparse
import html
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# a dark theme close to the landing page
BACKGROUND = "#12141c"
FOREGROUND = "#d6dae6"
PALETTE = {
    30: "#3b4052", 31: "#ff6b7f", 32: "#7ee2a8", 33: "#ffc861",
    34: "#6f86ff", 35: "#d58cff", 36: "#4fd6e0", 37: "#d6dae6",
    90: "#6b7189", 91: "#ff8496", 92: "#9af0bf", 93: "#ffd88a",
    94: "#8fa0ff", 95: "#e2a8ff", 96: "#7ae6ee", 97: "#ffffff",
}
CHAR_W = 8.4  # px per column at 14px monospace
LINE_H = 18
PAD = 18
TITLE_H = 34

SEQ = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])")


class Style:
    __slots__ = ("fg", "bold", "dim")

    def __init__(self, fg: str | None = None, bold: bool = False, dim: bool = False):
        self.fg, self.bold, self.dim = fg, bold, dim

    def copy(self) -> Style:
        return Style(self.fg, self.bold, self.dim)

    def key(self) -> tuple:
        return (self.fg, self.bold, self.dim)


def sgr(style: Style, params: str) -> Style:
    codes = [int(p) if p else 0 for p in params.split(";")] if params else [0]
    i = 0
    while i < len(codes):
        code = codes[i]
        if code == 0:
            style = Style()
        elif code == 1:
            style.bold = True
        elif code == 2:
            style.dim = True
        elif code == 22:
            style.bold = style.dim = False
        elif code == 39:
            style.fg = None
        elif code in PALETTE:
            style.fg = PALETTE[code]
        elif code == 38 and i + 4 < len(codes) and codes[i + 1] == 2:
            r, g, b = codes[i + 2 : i + 5]
            style.fg = f"#{r:02x}{g:02x}{b:02x}"
            i += 4
        elif code == 48 and i + 1 < len(codes) and codes[i + 1] == 2:
            i += 4  # backgrounds are ignored
        i += 1
    return style


def emulate(data: str, cols: int) -> list[list[tuple[str, Style]]]:
    """Replay *data* on a screen *cols* wide; returns the final lines."""
    lines: list[list[tuple[str, Style]]] = [[]]
    row = col = 0
    style = Style()
    pos = 0
    while pos < len(data):
        m = SEQ.match(data, pos)
        if m:
            params, cmd = m.groups()
            if cmd == "m":
                style = sgr(style.copy(), params)
            elif cmd == "A":
                row = max(0, row - int(params or 1))
            elif cmd == "B":
                row += int(params or 1)
            elif cmd == "K":
                mode = params or "0"
                line = lines[row]
                if mode == "2":
                    lines[row] = []
                elif mode == "0":
                    del line[col:]
            elif cmd == "J":
                del lines[row + 1 :]
                del lines[row][col:]
            elif cmd == "G":
                col = max(0, int(params or 1) - 1)
            pos = m.end()
            continue
        ch = data[pos]
        pos += 1
        if ch == "\x1b":  # an escape we do not know: skip it
            continue
        if ch == "\r":
            col = 0
        elif ch == "\n":
            row += 1
            col = 0
        elif ch == "\b":
            col = max(0, col - 1)
        elif ch == "\t":
            col = (col // 8 + 1) * 8
        elif ch >= " ":
            if col >= cols:
                row += 1
                col = 0
            while len(lines) <= row:
                lines.append([])
            line = lines[row]
            while len(line) < col:
                line.append((" ", Style()))
            cell = (ch, style.copy())
            if col < len(line):
                line[col] = cell
            else:
                line.append(cell)
            col += 1
        while len(lines) <= row:
            lines.append([])
    while lines and not "".join(c for c, _ in lines[-1]).strip():
        lines.pop()
    while lines and not "".join(c for c, _ in lines[0]).strip():
        lines.pop(0)
    return lines


def run(args: list[str], cols: int, rows: int, timeout: float) -> str:
    """Run xping (this checkout) in a pty *cols* x *rows*; its output."""
    import fcntl  # Unix only, like pty
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    env = dict(os.environ, COLUMNS=str(cols), LINES=str(rows), TERM="xterm-256color")
    env.pop("NO_COLOR", None)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "xping", *args],
        stdin=slave, stdout=slave, stderr=slave, env=env, cwd=ROOT, close_fds=True,
    )
    os.close(slave)
    out = bytearray()
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        elif proc.poll() is not None:
            break
    else:
        proc.terminate()
    proc.wait()
    os.close(master)
    return out.decode("utf-8", "replace")


def svg(lines: list[list[tuple[str, Style]]], cols: int, title: str) -> str:
    width = round(cols * CHAR_W + 2 * PAD)
    height = round(TITLE_H + len(lines) * LINE_H + 2 * PAD - 4)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        f"<title>{html.escape(title)}</title>",
        "<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"
        "'DejaVu Sans Mono',monospace;font-size:14px;white-space:pre}"
        ".b{font-weight:700}.d{opacity:.55}</style>",
        f'<rect width="{width}" height="{height}" rx="10" fill="{BACKGROUND}"/>',
        '<circle cx="20" cy="17" r="6" fill="#ff5f57"/>',
        '<circle cx="40" cy="17" r="6" fill="#febc2e"/>',
        '<circle cx="60" cy="17" r="6" fill="#28c840"/>',
        f'<text x="{width / 2:.0f}" y="22" fill="#6b7189" text-anchor="middle" '
        f'style="font-size:12px">{html.escape(title)}</text>',
    ]
    for n, line in enumerate(lines):
        y = TITLE_H + PAD + n * LINE_H
        spans = []
        run_text, run_style = "", None
        for ch, st in [*line, ("", None)]:
            if st is None or (run_style is not None and st.key() != run_style.key()):
                if run_text and run_style is not None:
                    spans.append((run_text, run_style))
                run_text, run_style = "", st
            if st is not None:
                if run_style is None:
                    run_style = st
                run_text += ch
        if not spans:
            continue
        parts = []
        for text, st in spans:
            cls = " ".join(c for c, on in (("b", st.bold), ("d", st.dim)) if on)
            attrs = f' fill="{st.fg or FOREGROUND}"'
            if cls:
                attrs += f' class="{cls}"'
            parts.append(f"<tspan{attrs}>{html.escape(text)}</tspan>")
        # textLength pins every line to the grid whatever monospace font the
        # viewer has, so columns and box drawing stay aligned
        length = sum(len(text) for text, _ in spans) * CHAR_W
        out.append(
            f'<text x="{PAD}" y="{y}" textLength="{length:.1f}" lengthAdjust="spacingAndGlyphs" '
            f'xml:space="preserve">{"".join(parts)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--cols", type=int, default=96)
    parser.add_argument("--rows", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--title", help="window title (default: the command)")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = [a for a in args.command if a != "--"]
    if not command:
        parser.error("give the xping arguments after --")
    data = run(command, args.cols, args.rows, args.timeout)
    lines = emulate(data, args.cols)
    title = args.title or "xping " + " ".join(command)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg(lines, args.cols, title), encoding="utf-8")
    print(f"{args.output}: {len(lines)} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
