"""~/.xping/config.toml — personal defaults (needs tomllib, Python 3.11+)."""

import importlib
import sys
from unittest.mock import patch

import pytest

from xping.cli import config as uc
from xping.cli.parser import build_parser

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11), reason="TOML needs Python 3.11+")

CONFIG = """
[defaults]
timeout = 3
ipv4 = true

[ping]
count = 2
max-latency = 150

[lookup]
doh = "cloudflare"

[ntp]
server = "time.example.net"

[propagation]
server = ["9.9.9.9"]
"""


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    def write(text: str):
        path = tmp_path / "config.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("XPING_CONFIG", str(path))
        return path

    return write


def _parse(argv):
    parser = build_parser()
    uc.apply(parser, uc.load())
    args = parser.parse_args(argv)
    uc.resolve_conflicts(build_parser(), args, argv)
    return args


def test_defaults_and_command_sections(cfg):
    cfg(CONFIG)
    ping = _parse(["ping", "h"])
    assert (ping.count, ping.timeout, ping.ipv4, ping.max_latency) == (2, 3.0, True, 150.0)
    assert _parse(["tcp", "h", "22"]).timeout == 3.0  # [defaults] reaches every command
    assert _parse(["ntp"]).server == "time.example.net"  # optional positional
    assert _parse(["propagation", "n"]).server == ["9.9.9.9"]  # repeatable option


def test_command_line_wins(cfg):
    cfg(CONFIG)
    assert _parse(["ping", "h", "-c", "9"]).count == 9
    six = _parse(["ping", "h", "-6"])
    assert six.ipv6 and not six.ipv4  # exclusive pair: CLI -6 drops ipv4 from the file
    server = _parse(["lookup", "h", "--server", "1.1.1.1"])
    assert server.server == "1.1.1.1" and server.doh is None
    assert _parse(["lookup", "h"]).doh == "cloudflare"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[pingg]\ncount = 2\n", "unknown section [pingg]"),
        ("[ping]\ncuont = 2\n", "[ping] has no option 'cuont'"),
        ("[ping]\ncount = 'many'\n", "'many' is not a valid int"),
        ("[tcp]\nport = 1\n", "has no option 'port'"),  # required positionals can't default
        ("[trace]\nasn = 'yes'\n", "must be true or false"),
        ("[listen]\nproto = 'sctp'\n", "must be one of tcp, udp"),
        ("[defaults]\nfoo = 1\n", "no command has option(s): foo"),
        ("count = 2\n", "must be a [section]"),
        ("[ping\n", "invalid TOML"),
        ("[completion]\ninstall = true\n", "has no option 'install'"),
    ],
)
def test_errors_name_the_problem(cfg, text, message):
    path = cfg(text)
    with pytest.raises(uc.ConfigError) as err:
        uc.apply(build_parser(), uc.load())
    assert message in str(err.value) and str(path) in str(err.value)


def test_missing_disabled_and_env(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("XPING_CONFIG", str(tmp_path / "nope.toml"))
    assert not uc.load().loaded
    monkeypatch.setenv("XPING_CONFIG", "none")
    assert uc.load().disabled
    monkeypatch.delenv("XPING_CONFIG")
    assert uc.config_path() == uc.DEFAULT_PATH


def test_main_applies_config_and_reports_errors(cfg, capsys):
    main_mod = importlib.import_module("xping.cli.main")

    cfg("[ping]\ncount = 3\n")
    seen = {}
    with patch("sys.argv", ["xping", "ping", "h"]), patch.dict(
        main_mod._DISPATCH, {"ping": lambda args: seen.setdefault("count", args.count) and True}
    ), pytest.raises(SystemExit) as code:
        main_mod.main()
    assert seen["count"] == 3 and code.value.code == 0

    cfg("[ping]\ncuont = 3\n")
    with patch("sys.argv", ["xping", "ping", "h"]), pytest.raises(SystemExit) as code:
        main_mod.main()
    assert code.value.code == 2 and "config error" in capsys.readouterr().err
    # `xping config` still runs and explains the problem
    with patch("sys.argv", ["xping", "config"]), pytest.raises(SystemExit) as code:
        main_mod.main()
    assert code.value.code == 1 and "has no option 'cuont'" in capsys.readouterr().out


def test_bare_host_uses_ping_section(cfg):
    main_mod = importlib.import_module("xping.cli.main")
    from xping.models.ping import PingResult

    cfg("[ping]\ncount = 4\ntimeout = 1.5\n")
    with (
        patch("sys.argv", ["xping", "198.51.100.7"]),
        patch("xping.diagnostics.ping.ping", return_value=PingResult("h", "198.51.100.7", 4, [1.0] * 4)) as ping,
        patch("sys.stdout.isatty", return_value=False),
        pytest.raises(SystemExit),
    ):
        main_mod.main()
    assert ping.call_args.kwargs["count"] == 4 and ping.call_args.kwargs["timeout"] == 1.5


def test_config_command_and_example(cfg, capsys, tmp_path):
    from xping.cli import commands

    path = cfg(uc.EXAMPLE)  # the example itself must be valid
    uc.apply(build_parser(), uc.load())
    assert commands.cmd_config(build_parser().parse_args(["config"])) is True
    out = capsys.readouterr().out
    assert str(path) in out and "count" in out and "10" in out
    commands.cmd_config(build_parser().parse_args(["config", "--example"]))
    assert capsys.readouterr().out == uc.EXAMPLE
