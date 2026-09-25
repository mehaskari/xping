"""Tests for CLI dispatch and command handlers."""

import pytest
from unittest.mock import MagicMock, patch

from xping.cli.export import emit_export
from xping.cli.parser import build_parser
from xping.models.lookup import DnsResult
from xping.models.ping import PingResult
from xping.models.trace import Hop


@pytest.mark.parametrize(
    ("command", "handler", "extra", "mock_target", "return_value"),
    [
        ("trace", "cmd_trace", [], "xping.cli.commands.trace", [Hop(ttl=1, host="gw", ip="10.0.0.1", rtts=[1.0])]),
        ("lookup", "cmd_lookup", ["--full"], "xping.cli.commands.lookup", DnsResult(host="h", ipv4=["1.1.1.1"])),
    ],
)
def test_cmd_export_json(capsys, command, handler, extra, mock_target, return_value):
    from xping.cli import commands

    args = build_parser().parse_args([command, "example.com", *extra, "--json"])
    with patch(mock_target, return_value=return_value):
        getattr(commands, handler)(args)
    out = capsys.readouterr().out
    assert out.strip()


def test_emit_export_csv(capsys):
    args = build_parser().parse_args(["ping", "1.1.1.1", "--csv"])
    emit_export(PingResult(host="1.1.1.1", ip="1.1.1.1", count=1, rtts=[1.0]), args)
    assert "field,value" in capsys.readouterr().out


def test_main_without_command_exits(capsys):
    from xping.cli.main import main

    with patch("sys.argv", ["xping"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0
    assert "network diagnostics" in capsys.readouterr().out


def test_main_handles_keyboard_interrupt(capsys):
    from xping.cli.main import _DISPATCH, main

    # Patch the dict object itself: the dotted string "xping.cli.main._DISPATCH"
    # resolves to the main() function on Python 3.10, since xping.cli re-exports it.
    with patch("sys.argv", ["xping", "ping", "1.1.1.1"]):
        with patch.dict(_DISPATCH, {"ping": MagicMock(side_effect=KeyboardInterrupt)}):
            with pytest.raises(SystemExit) as exc:
                main()
    assert exc.value.code == 130


def test_main_handles_generic_error(capsys):
    from xping.cli.main import _DISPATCH, main

    # Patch the dict object itself: the dotted string "xping.cli.main._DISPATCH"
    # resolves to the main() function on Python 3.10, since xping.cli re-exports it.
    with patch("sys.argv", ["xping", "ping", "1.1.1.1"]):
        with patch.dict(_DISPATCH, {"ping": MagicMock(side_effect=RuntimeError("boom"))}):
            with pytest.raises(SystemExit) as exc:
                main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "boom" in captured.out or "boom" in captured.err


def _subcommand_parsers():
    import argparse

    parser = build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return parser, action.choices


def test_command_lists_stay_in_sync():
    """Parser, dispatch table, completion, and --help epilog must list the same commands."""
    from xping.cli import completion
    from xping.cli.main import _DISPATCH

    parser, subparsers = _subcommand_parsers()
    assert set(subparsers) == set(_DISPATCH)
    assert set(completion._COMMANDS) == set(_DISPATCH)
    for command in _DISPATCH:
        assert f"\n  {command} " in parser.epilog, f"{command} missing from --help epilog"


def test_completion_flags_match_parser():
    from xping.cli import completion

    _, subparsers = _subcommand_parsers()
    for command, sub in subparsers.items():
        long_opts = {
            opt
            for action in sub._actions
            for opt in action.option_strings
            if opt.startswith("--") and opt != "--help"
        }
        assert set(completion._FLAGS.get(command, [])) == long_opts, command


def test_bare_host_detection():
    from xping.cli.main import _is_bare_host

    assert _is_bare_host(["8.8.8.8"]) == "8.8.8.8"
    assert _is_bare_host(["ping"]) is None
    assert _is_bare_host(["--help"]) is None
    assert _is_bare_host(["ping", "8.8.8.8"]) is None


def test_ping_watch_rejects_export_flags():
    from xping.cli import commands

    args = build_parser().parse_args(["ping", "example.com", "--watch", "--json"])
    with patch("xping.cli.commands.ping_watch") as mock_watch:
        with pytest.raises(ValueError, match="--watch"):
            commands.cmd_ping(args)
    mock_watch.assert_not_called()
