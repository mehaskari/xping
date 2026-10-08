"""xping monitor --install-service / --uninstall-service / --service-status
(service files are written under a temporary home; launchctl and systemctl
are faked)."""

import importlib
import plistlib
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from xping.diagnostics import service


class Runner:
    def __init__(self, outputs=None):
        self.calls, self.outputs = [], outputs or {}

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        out = next((v for k, v in self.outputs.items() if k in " ".join(cmd)), "")
        return subprocess.CompletedProcess(cmd, 0, out, "")


def _args(**over):
    base = dict(targets=[], every=30.0, workers=8, save=True, fail_after=3, recover_after=1,
                notify=False, webhook=None)
    return SimpleNamespace(**{**base, **over})


def test_monitor_arguments_rebuild_the_command(tmp_path):
    checks = tmp_path / "c.toml"
    checks.write_text("")
    assert service.monitor_arguments(_args(targets=[str(checks)], webhook="https://h.test/x")) == [
        "monitor", str(checks.resolve()), "--every", "30", "--save", "--fail-after", "3",
        "--webhook", "https://h.test/x",
    ]
    assert service.monitor_arguments(_args(targets=["1.1.1.1", "db:5432"], save=False,
                                           fail_after=1, every=10.0, notify=True)) == [
        "monitor", "1.1.1.1", "db:5432", "--every", "10", "--notify",
    ]


def test_launchd_plist_is_valid_and_runs_forever(tmp_path):
    data = service.launchd_plist(["/opt/homebrew/bin/xping", "monitor", "--save"], tmp_path / "m.log")
    plist = plistlib.loads(data)
    assert plist["Label"] == service.LABEL and plist["RunAtLoad"] and plist["KeepAlive"]
    assert plist["ProgramArguments"][-2:] == ["monitor", "--save"]
    assert plist["StandardOutPath"] == plist["StandardErrorPath"] == str(tmp_path / "m.log")
    if sys.platform == "darwin":
        path = tmp_path / "x.plist"
        path.write_bytes(data)
        assert subprocess.run(["plutil", "-lint", str(path)], capture_output=True).returncode == 0


def test_systemd_unit_quotes_every_argument(tmp_path):
    unit = service.systemd_unit(["/usr/bin/xping", "monitor", "a b", "50%", "$HOME"], tmp_path / "m.log")
    exec_line = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    assert exec_line == 'ExecStart="/usr/bin/xping" "monitor" "a b" "50%%" "$$HOME"'
    assert "Restart=always" in unit and f"StandardOutput=append:{tmp_path / 'm.log'}" in unit


@pytest.mark.parametrize("kind", ["launchd", "systemd"])
def test_install_status_uninstall(tmp_path, kind):
    run = Runner({
        "launchctl print": "\tstate = running\n\tpid = 4242\n\t\tstate = active\n",
        "systemctl --user show": "ActiveState=active\nMainPID=4242\n",
    })
    with patch.object(service, "xping_command", return_value=["/opt/x/bin/xping"]):
        state = service.install(["monitor", "--save"], home=tmp_path, kind=kind, run=run)
    assert state.installed and state.running and state.pid == 4242
    assert state.command == ["/opt/x/bin/xping", "monitor", "--save"]
    assert state.path.exists() and state.log == tmp_path / ".xping" / "monitor.log"
    starts = [c for c in run.calls if c[:2] in (["launchctl", "bootstrap"], ["systemctl", "--user"])]
    assert starts
    # installing again replaces the running one
    with patch.object(service, "xping_command", return_value=["/opt/x/bin/xping"]):
        service.install(["monitor"], home=tmp_path, kind=kind, run=run)
    if kind == "launchd":
        assert any(c[:2] == ["launchctl", "bootout"] for c in run.calls)
    assert service.uninstall(home=tmp_path, kind=kind, run=run) is True
    assert not state.path.exists()
    assert service.uninstall(home=tmp_path, kind=kind, run=run) is False
    assert not service.status(home=tmp_path, kind=kind, run=run).installed


def test_failed_start_is_reported(tmp_path):
    def run(cmd):
        return subprocess.CompletedProcess(cmd, 5, "", "Bootstrap failed: 5: Input/output error")

    with pytest.raises(service.ServiceError, match="Input/output error"):
        service.install(["monitor"], home=tmp_path, kind="launchd", run=run)


def test_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(service.ServiceError, match="macOS and Linux"):
        service.platform_kind()


def _main(argv, capsys):
    main_mod = importlib.import_module("xping.cli.main")
    with patch("sys.argv", ["xping", *argv]), pytest.raises(SystemExit) as exc:
        main_mod.main()
    return exc.value.code, capsys.readouterr()


def test_cli_install_validates_first_and_reports(tmp_path, capsys):
    calls = []

    def fake_install(monitor_args):
        calls.append(monitor_args)
        return service.ServiceStatus(True, True, 99, tmp_path / "s.plist",
                                     ["/x/xping", *monitor_args], tmp_path / "m.log")

    with patch.object(service, "install", fake_install):
        code, captured = _main(["monitor", "1.1.1.1", "db:5432", "--save", "--install-service"], capsys)
        assert code == 0 and calls[0][:3] == ["monitor", "1.1.1.1", "db:5432"]
        assert "runs in the background (pid 99)" in captured.out
        assert "xping monitor --uninstall-service" in captured.out
        code, captured = _main(["monitor", "db:http", "--install-service"], capsys)
        assert code == 2 and len(calls) == 1  # invalid target: nothing installed
        code, _ = _main(["monitor", "1.1.1.1", "--rounds", "3", "--install-service"], capsys)
        assert code == 2


def test_cli_status_and_uninstall(tmp_path, capsys):
    off = service.ServiceStatus(False, False, None, tmp_path / "s", [], tmp_path / "m.log")
    with patch.object(service, "status", return_value=off), patch.object(service, "uninstall", return_value=False):
        code, captured = _main(["monitor", "--service-status"], capsys)
        assert code == 1 and "not installed" in captured.out
        code, captured = _main(["monitor", "--uninstall-service"], capsys)
        assert code == 0 and "was not installed" in captured.out
    code, _ = _main(["monitor", "--install-service", "--service-status"], capsys)
    assert code == 2  # one service action at a time
