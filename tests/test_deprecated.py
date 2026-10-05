"""Short options that meant something else in one command still work until
2.0, with a warning — rewritten before parsing."""

import pytest

from xping.cli import deprecated
from xping.cli.parser import build_parser


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["trace", "h", "-p", "5"], ["trace", "h", "--probes", "5"]),
        (["trace", "h", "-p5"], ["trace", "h", "--probes=5"]),
        (["propagation", "example.com", "-t", "MX"], ["propagation", "example.com", "--type", "MX"]),
        (["ping", "h", "-w"], ["ping", "h", "--watch"]),
        (["wifi", "-i", "en0"], ["wifi", "--interface", "en0"]),
    ],
)
def test_old_spelling_is_rewritten_with_a_warning(argv, expected):
    warnings = []
    assert deprecated.rewrite(argv, warnings.append) == expected
    assert len(warnings) == 1 and "removed in 2.0" in warnings[0]
    build_parser().parse_args(expected)  # and the result parses


@pytest.mark.parametrize(
    "argv",
    [
        ["portscan", "h", "-p", "22", "-w", "8"],  # the meaning everywhere else
        ["ping", "h", "-i", "0.2", "-t", "1"],
        ["trace", "h", "--", "-p"],
        ["ping"],
        [],
    ],
)
def test_other_options_are_untouched(argv):
    warnings = []
    assert deprecated.rewrite(argv, warnings.append) == argv
    assert warnings == []


@pytest.mark.parametrize(
    "argv",
    [["trace", "h", "-p", "5"], ["propagation", "h", "-t", "MX"], ["ping", "h", "-w"], ["wifi", "-i", "x"]],
)
def test_new_parser_rejects_the_old_spelling(argv, capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_new_short_options():
    assert build_parser().parse_args(["propagation", "h", "-r", "mx"]).rtype == "MX"
    assert build_parser().parse_args(["wifi", "-I", "wlan0"]).interface == "wlan0"


def test_main_warns_on_stderr_and_keeps_stdout_clean(monkeypatch, capsys):
    import importlib
    from unittest.mock import patch

    main_mod = importlib.import_module("xping.cli.main")
    with (
        patch("sys.argv", ["xping", "trace", "h", "-p", "2", "-q"]),
        patch("xping.cli.commands.trace", return_value=[]) as fake,
        pytest.raises(SystemExit),
    ):
        main_mod.main()
    assert fake.call_args.kwargs["probes"] == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "trace: -p is deprecated" in captured.err and "--probes" in captured.err
