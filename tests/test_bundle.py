"""Tests for bundle diagnostics and CLI export flags."""

import pytest
from unittest.mock import patch

from xping.cli.parser import build_parser
from xping.diagnostics.bundle import run_bundle
from xping.models.lookup import DnsResult
from xping.models.ping import PingResult
from xping.models.tcp import TcpResult


def test_run_bundle_collects_sections():
    with patch("xping.diagnostics.bundle.lookup", return_value=DnsResult(host="h", ipv4=["1.1.1.1"])):
        with patch("xping.diagnostics.bundle.ping", return_value=PingResult(host="h", ip="1.1.1.1", count=1, rtts=[1.0])):
            with patch("xping.diagnostics.bundle.trace", return_value=[]):
                with patch("xping.diagnostics.bundle.tcp", return_value=TcpResult(host="h", port=443, ip="1.1.1.1")):
                    result = run_bundle("example.com", quiet=True)
    assert result.host == "example.com"
    assert result.lookup is not None
    assert len(result.tcp) == 2


def test_cli_accepts_export_flags():
    parser = build_parser()
    args = parser.parse_args(["ping", "1.1.1.1", "--json"])
    assert args.json is True
    assert args.command == "ping"


def test_cmd_ping_json_output(capsys):
    from xping.cli.commands import cmd_ping
    parser = build_parser()
    args = parser.parse_args(["ping", "1.1.1.1", "-c", "1", "--json"])
    with patch("xping.cli.commands.ping", return_value=PingResult(host="1.1.1.1", ip="1.1.1.1", count=1, rtts=[1.0])):
        cmd_ping(args)
    out = capsys.readouterr().out
    assert '"host": "1.1.1.1"' in out


def test_cmd_all_markdown_output(capsys):
    from xping.cli.commands import cmd_all
    from xping.models.bundle import BundleResult
    args = build_parser().parse_args(["all", "example.com", "--markdown"])
    bundle = BundleResult(host="example.com", lookup=DnsResult(host="example.com", ipv4=["1.1.1.1"]))
    with patch("xping.cli.commands.run_bundle", return_value=bundle):
        cmd_all(args)
    assert "# XPing Result" in capsys.readouterr().out


def test_cli_main_version(capsys):
    from xping.cli.main import main
    with patch("sys.argv", ["xping", "-V"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0
    assert "xping" in capsys.readouterr().out
