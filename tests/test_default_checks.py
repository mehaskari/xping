"""The default check file (~/.xping/checks.toml), check --init, and
xping monitor HOST HOST:PORT URL without a file."""

import importlib
import sys
from unittest.mock import patch

import pytest

from xping.diagnostics import check as check_diag

# --init writes TOML where Python can read it (3.11+), JSON on 3.10
STARTER = "checks.toml" if sys.version_info >= (3, 11) else "checks.json"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(check_diag, "DEFAULT_DIR", tmp_path / ".xping")
    return tmp_path / ".xping"


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("1.1.1.1", ("ping", "1.1.1.1", None)),
        ("router.local", ("ping", "router.local", None)),
        ("db.internal:5432", ("tcp", "db.internal", 5432)),
        ("2001:db8::1", ("ping", "2001:db8::1", None)),
        ("[2001:db8::1]:22", ("tcp", "2001:db8::1", 22)),
        ("https://x.test/health", ("http", "https://x.test/health", None)),
    ],
)
def test_targets_become_checks(target, expected):
    entry = check_diag.entries_from_targets([target])[0]
    assert (entry["type"], entry.get("host") or entry.get("url"), entry.get("port")) == expected
    assert entry["name"] == target


@pytest.mark.parametrize("target", ["db:0", "db:99999", "db:http"])
def test_bad_ports(target):
    with pytest.raises(check_diag.ConfigError, match="port"):
        check_diag.entries_from_targets([target])


def test_missing_default_file_explains_what_to_do(home):
    with pytest.raises(check_diag.NoCheckFile) as exc:
        check_diag.require_default()
    assert "xping check --init" in str(exc.value) and "xping monitor 1.1.1.1" in str(exc.value)


def test_init_creates_once_and_never_overwrites(home):
    path, created = check_diag.init_file(gateway="192.168.1.1")
    assert created and path == home / STARTER
    entries = check_diag.load_config(str(path))
    assert [e["host"] for e in entries[:3]] == ["192.168.1.1", "1.1.1.1", "8.8.8.8"]
    assert all(e["fail_after"] == 3 for e in entries)
    path.write_text("# mine\n")
    assert check_diag.init_file() == (path, False) and path.read_text() == "# mine\n"
    assert check_diag.require_default() == path


def test_init_without_gateway_and_json_fallback(home, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_tomllib(name, *args, **kwargs):
        if name == "tomllib":
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_tomllib)
    path, created = check_diag.init_file(gateway=None)
    monkeypatch.setattr(builtins, "__import__", real_import)
    assert created and path.name == "checks.json"
    entries = check_diag.load_config(str(path))
    assert entries[0]["name"] == "Internet (Cloudflare DNS)"  # no router without a gateway
    assert check_diag.default_file() == path  # only the JSON exists: it is the default


def _main(argv, capsys):
    main_mod = importlib.import_module("xping.cli.main")
    with patch("sys.argv", ["xping", *argv]), pytest.raises(SystemExit) as exc:
        main_mod.main()
    return exc.value.code, capsys.readouterr()


def test_cli_monitor_without_file_or_targets(home, capsys):
    code, captured = _main(["monitor"], capsys)
    assert code == 2 and "xping check --init" in captured.err


def test_cli_check_init_and_default_file(home, capsys):
    with patch("xping.diagnostics.net.net") as fake_net:
        fake_net.return_value.gateway_ipv4 = "10.0.0.1"
        code, captured = _main(["check", "--init"], capsys)
    assert code == 0 and "created" in captured.out and (home / STARTER).exists()
    with patch("xping.cli.commands.run_checks") as fake_run:
        fake_run.return_value = None
        _main(["check", "-q"], capsys)
    assert fake_run.call_args.args[0] == str(home / STARTER)


def test_cli_monitor_targets_and_file(home, tmp_path, capsys):
    calls = []

    def fake_monitor(path, **kwargs):
        calls.append((path, kwargs.get("entries")))
        from xping.models.monitor import MonitorResult

        return MonitorResult(source=path or "targets", started=0)

    with patch("xping.diagnostics.monitor.monitor", fake_monitor):
        _main(["monitor", "1.1.1.1", "db:5432", "-q"], capsys)
        own = tmp_path / "mine.json"
        own.write_text('{"checks": [{"type": "ping", "host": "a"}]}')
        _main(["monitor", str(own), "-q"], capsys)
    (path, entries), (file_path, no_entries) = calls
    assert path is None and [e["type"] for e in entries] == ["ping", "tcp"]
    assert file_path == str(own) and no_entries is None
