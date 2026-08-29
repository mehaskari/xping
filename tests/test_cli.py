"""Tests for CLI dispatch and command handlers."""

import pytest
from unittest.mock import patch

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
    from xping.cli.main import main

    with patch("sys.argv", ["xping", "ping", "1.1.1.1"]):
        with patch("xping.cli.commands.cmd_ping", side_effect=KeyboardInterrupt):
            with pytest.raises(SystemExit) as exc:
                main()
    assert exc.value.code == 130


def test_main_handles_generic_error(capsys):
    from xping.cli.main import main

    with patch("sys.argv", ["xping", "ping", "1.1.1.1"]):
        with patch("xping.cli.commands.cmd_ping", side_effect=RuntimeError("boom")):
            with pytest.raises(SystemExit) as exc:
                main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "boom" in captured.out or "boom" in captured.err
