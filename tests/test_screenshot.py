"""scripts/screenshot.py: the terminal emulator and the SVG it writes
(no command is run)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "scripts" / "screenshot.py").exists():  # not shipped in the PyPI sdist
    pytest.skip("scripts/screenshot.py is not in this source tree", allow_module_level=True)
spec = importlib.util.spec_from_file_location("screenshot", ROOT / "scripts" / "screenshot.py")
screenshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screenshot)


def text(lines):
    return ["".join(ch for ch, _ in line).rstrip() for line in lines]


def test_carriage_return_and_clear_keep_only_the_final_text():
    data = "\r\n  ⠋  working…\r" + " " * 20 + "\r  ✔  done\r\nnext\n"
    assert text(screenshot.emulate(data, 40)) == ["  ✔  done", "next"]


def test_cursor_up_and_erase_line_redraw_in_place():
    data = "a\nold 1\nold 2\n\x1b[1A\x1b[2K\x1b[1A\x1b[2Knew 1\nnew 2\n"
    assert text(screenshot.emulate(data, 40)) == ["a", "new 1", "new 2"]


def test_long_lines_wrap_at_the_width():
    assert text(screenshot.emulate("abcdef\n", 4)) == ["abcd", "ef"]


def test_colours_bold_and_dim():
    lines = screenshot.emulate("\x1b[38;2;0;210;190m\x1b[1mA\x1b[0m\x1b[2m\x1b[31mB\x1b[0mC", 10)
    a, b, c = (style for _, style in lines[0])
    assert (a.fg, a.bold, a.dim) == ("#00d2be", True, False)
    assert (b.fg, b.bold, b.dim) == (screenshot.PALETTE[31], False, True)
    assert (c.fg, c.bold, c.dim) == (None, False, False)


def test_svg_escapes_text_and_names_the_window():
    svg = screenshot.svg(screenshot.emulate("<a & b>\n", 20), 20, "xping <x>")
    assert "&lt;a &amp; b&gt;" in svg and "<title>xping &lt;x&gt;</title>" in svg
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")


def test_options_before_the_separator_stay_ours(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, cols, rows, timeout):
        seen.update(command=command, cols=cols, timeout=timeout)
        return "hello\n", 0

    monkeypatch.setattr(screenshot, "run", fake_run)
    out = tmp_path / "x.svg"
    argv = [str(out), "--cols", "92", "--timeout", "5", "--", "http", "--cols", "x"]
    assert screenshot.main(argv) == 0
    assert seen == {"command": ["http", "--cols", "x"], "cols": 92, "timeout": 5.0}
    assert "hello" in out.read_text()


def test_a_usage_error_writes_no_screenshot(monkeypatch, tmp_path):
    monkeypatch.setattr(screenshot, "run", lambda *a: ("usage: xping …\n", 2))
    out = tmp_path / "x.svg"
    assert screenshot.main([str(out), "--", "nonsense"]) == 2
    assert not out.exists()


def test_stop_at_drops_that_line_and_the_rest():
    lines = screenshot.emulate("a\nb\n\n── Response headers ──\nx: 1\n", 40)
    assert text(screenshot.trim(lines, "Response headers")) == ["a", "b"]
    assert text(screenshot.trim(lines, "not there")) == text(lines)
