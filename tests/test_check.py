"""xping check — batch checks from a TOML/JSON file."""

import json
import sys
from unittest.mock import patch

import pytest

from xping.cli.verdict import evaluate
from xping.diagnostics import check as check_diag
from xping.models.ping import PingResult
from xping.models.tcp import TcpAttempt, TcpResult

needs_tomllib = pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib is 3.11+")


def _write(tmp_path, name, text, encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return str(path)


@needs_tomllib
def test_example_config_is_valid(tmp_path):
    entries = check_diag.load_config(_write(tmp_path, "c.toml", check_diag.EXAMPLE))
    assert [e["type"] for e in entries] == ["ping", "tcp", "http", "tls", "dnscheck", "propagation"]
    assert all(e["timeout"] == 3 for e in entries)  # [defaults] merged into every check


def test_json_config_and_default_names(tmp_path):
    cfg = {"defaults": {"timeout": 1}, "checks": [{"type": "TCP", "host": "db", "port": 5432}]}
    entries = check_diag.load_config(_write(tmp_path, "c.json", json.dumps(cfg)))
    assert entries[0]["type"] == "tcp" and entries[0]["name"] == "tcp db"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"checks": []}', "at least one"),
        ('{"checks": [{"type": "nope"}]}', "unknown type"),
        ('{"checks": [{"type": "tcp", "host": "h"}]}', "missing port"),
        ("not json", "invalid JSON"),
        ('{"checks": ["x"]}', "must be a table"),
    ],
)
def test_config_errors(tmp_path, text, message):
    with pytest.raises(check_diag.ConfigError, match=message):
        check_diag.load_config(_write(tmp_path, "c.json", text))


def test_missing_file():
    with pytest.raises(check_diag.ConfigError, match="cannot read"):
        check_diag.load_config("/definitely/not/here.json")


def test_run_checks_judges_with_thresholds_and_isolates_errors(tmp_path, capsys):
    cfg = {
        "checks": [
            {"name": "fast ping", "type": "ping", "host": "a", "max_latency": 50},
            {"name": "slow ping", "type": "ping", "host": "b", "max_latency": 50},
            {"name": "db", "type": "tcp", "host": "prod-db", "port": 5432},
            {"name": "broken", "type": "http", "url": "https://x"},
        ]
    }
    path = _write(tmp_path, "c.json", json.dumps(cfg))

    def fake_ping(host, **_kw):
        rtt = 10.0 if host == "a" else 200.0
        return PingResult(host=host, ip="1.2.3.4", count=1, rtts=[rtt])

    def fake_tcp(host, port, **_kw):
        assert host == "10.0.0.5"  # profile name resolved
        return TcpResult(host=host, port=port, ip=host, attempts=[TcpAttempt(1, True, 4.0)])

    with (
        patch("xping.diagnostics.ping.ping", side_effect=fake_ping),
        patch("xping.diagnostics.tcp.tcp", side_effect=fake_tcp),
        patch("xping.diagnostics.http.http_diagnose", side_effect=RuntimeError("kaboom")),
        patch.object(check_diag.profile_diag, "resolve_target", side_effect=lambda v: {"prod-db": "10.0.0.5"}.get(v, v)),
        patch("sys.stdout.isatty", return_value=False),
        patch("xping.render.COLOR", False),
    ):
        report = check_diag.run_checks(path)
    by_name = {o.name: o for o in report.outcomes}
    assert by_name["fast ping"].ok and not by_name["slow ping"].ok
    assert "max-latency" in by_name["slow ping"].detail
    assert by_name["db"].ok and by_name["db"].target == "prod-db:5432"  # shown as configured
    assert not by_name["broken"].ok and by_name["broken"].detail == "error: kaboom"
    assert report.failed == 2 and evaluate(report)
    out = capsys.readouterr().out
    assert "2 of 4 checks failed" in out


def test_cli_example_and_missing_file(capsys):
    from xping.cli import commands
    from xping.cli.errors import UsageError
    from xping.cli.parser import build_parser

    assert commands.cmd_check(build_parser().parse_args(["check", "--example"])) is True
    assert "[[check]]" in capsys.readouterr().out
    with pytest.raises(UsageError):
        commands.cmd_check(build_parser().parse_args(["check"]))


def test_example_is_ascii():
    assert check_diag.EXAMPLE.isascii()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_config_encodings(tmp_path, encoding):
    """PowerShell 5 redirection writes UTF-16 with a BOM; UTF-8 BOMs are common too."""
    cfg = '{"checks": [{"type": "ping", "host": "h", "name": "caf\u00e9"}]}'
    entries = check_diag.load_config(_write(tmp_path, "c.json", cfg, encoding))
    assert entries[0]["name"] == "caf\u00e9"


def test_config_undecodable(tmp_path):
    path = tmp_path / "c.json"
    path.write_bytes(b'{"checks": [\x97]}')
    with pytest.raises(check_diag.ConfigError, match="not UTF-8"):
        check_diag.load_config(str(path))
