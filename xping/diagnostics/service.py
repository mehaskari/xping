"""
xping.diagnostics.service — run ``xping monitor`` as a background service.

``xping monitor --install-service`` writes a per-user service that starts
the same monitor at login (and restarts it if it stops), with its output in
~/.xping/monitor.log:

  macOS  a LaunchAgent, ~/Library/LaunchAgents/<LABEL>.plist (launchctl)
  Linux  a systemd user unit, ~/.config/systemd/user/<UNIT> (systemctl --user)

No root is needed and nothing outside the user's home is touched.
``--uninstall-service`` stops and removes it, ``--service-status`` reports
whether it runs.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

LABEL = "io.github.mehaskari.xping.monitor"
UNIT = "xping-monitor.service"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=30, check=False)


class ServiceError(RuntimeError):
    """The service could not be installed, removed or queried."""


@dataclass
class ServiceStatus:
    installed: bool
    running: bool
    pid: int | None
    path: Path
    command: list[str]
    log: Path


def _gui_domain() -> str:
    """launchd's per-user domain, gui/<uid> (os.getuid does not exist on
    Windows, where only the tests get this far)."""
    getuid = getattr(os, "getuid", None)
    return f"gui/{getuid() if getuid else 0}"


def platform_kind() -> str:
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux"):
        return "systemd"
    raise ServiceError("a background service is supported on macOS and Linux only")


def log_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".xping" / "monitor.log"


def service_path(kind: str, home: Path | None = None) -> Path:
    home = home or Path.home()
    if kind == "launchd":
        return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    return home / ".config" / "systemd" / "user" / UNIT


def xping_command() -> list[str]:
    """How the service starts xping. The ``xping`` launcher on PATH is
    preferred: it survives upgrades (Homebrew moves the Python it runs in to
    a new versioned directory, but /opt/homebrew/bin/xping stays)."""
    found = shutil.which("xping")
    if found:
        return [str(Path(found).absolute())]
    return [sys.executable, "-m", "xping"]


def monitor_arguments(args) -> list[str]:
    """The monitor command line equivalent to *args* (a parsed namespace),
    with a check file made absolute so the service finds it from anywhere."""
    targets = list(args.targets or [])
    if len(targets) == 1 and (
        targets[0].lower().endswith((".toml", ".json")) or Path(targets[0]).is_file()
    ):
        targets = [str(Path(targets[0]).expanduser().resolve())]
    out = ["monitor", *targets, "--every", f"{args.every:g}"]
    if args.workers != 8:
        out += ["--workers", str(args.workers)]
    if args.save:
        out.append("--save")
    if args.fail_after != 1:
        out += ["--fail-after", str(args.fail_after)]
    if args.recover_after != 1:
        out += ["--recover-after", str(args.recover_after)]
    if args.notify:
        out.append("--notify")
    if args.webhook:
        out += ["--webhook", args.webhook]
    return out


def launchd_plist(command: list[str], log: Path) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": command,
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 30,  # at most one restart every 30 s
            "StandardOutPath": str(log),
            "StandardErrorPath": str(log),
            "StandardInPath": "/dev/null",
            "EnvironmentVariables": {
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "PYTHONUNBUFFERED": "1",
            },
            "ProcessType": "Background",
        }
    )


def _systemd_quote(arg: str) -> str:
    """Quote one ExecStart argument for systemd ("%" and "$" are special)."""
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("%", "%%").replace("$", "$$")
    return f'"{escaped}"'


def systemd_unit(command: list[str], log: Path) -> str:
    return (
        "[Unit]\n"
        "Description=xping monitor (network checks, see: xping monitor --help)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={' '.join(_systemd_quote(a) for a in command)}\n"
        "Restart=always\n"
        "RestartSec=30\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        "StandardInput=null\n"
        f"StandardOutput=append:{log}\n"
        f"StandardError=append:{log}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _check(proc: subprocess.CompletedProcess, what: str) -> None:
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise ServiceError(f"{what} failed" + (f": {detail[-1]}" if detail else ""))


def install(
    monitor_args: list[str],
    home: Path | None = None,
    kind: str | None = None,
    run: Runner = _run,
) -> ServiceStatus:
    """Write the service, (re)start it and return its status."""
    kind = kind or platform_kind()
    path = service_path(kind, home)
    log = log_path(home)
    command = xping_command() + monitor_args
    path.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    if kind == "launchd":
        domain = _gui_domain()
        if path.exists():  # replace a running one
            run(["launchctl", "bootout", f"{domain}/{LABEL}"])
        path.write_bytes(launchd_plist(command, log))
        _check(run(["launchctl", "bootstrap", domain, str(path)]), "launchctl bootstrap")
    else:
        path.write_text(systemd_unit(command, log), encoding="utf-8")
        _check(run(["systemctl", "--user", "daemon-reload"]), "systemctl daemon-reload")
        _check(run(["systemctl", "--user", "enable", UNIT]), "systemctl enable")
        _check(run(["systemctl", "--user", "restart", UNIT]), "systemctl restart")
    return status(home, kind, run)


def uninstall(home: Path | None = None, kind: str | None = None, run: Runner = _run) -> bool:
    """Stop and remove the service; False when none was installed."""
    kind = kind or platform_kind()
    path = service_path(kind, home)
    if not path.exists():
        return False
    if kind == "launchd":
        run(["launchctl", "bootout", f"{_gui_domain()}/{LABEL}"])
        path.unlink()
    else:
        run(["systemctl", "--user", "disable", "--now", UNIT])
        path.unlink()
        run(["systemctl", "--user", "daemon-reload"])
    return True


def _installed_command(kind: str, path: Path) -> list[str]:
    """The command an installed service runs ([] when it cannot be read)."""
    try:
        if kind == "launchd":
            return list(plistlib.loads(path.read_bytes()).get("ProgramArguments", []))
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError, plistlib.InvalidFileException):
        return []
    for line in lines:
        if line.startswith("ExecStart="):
            return shlex.split(line[len("ExecStart=") :].replace("$$", "$").replace("%%", "%"))
    return []


def status(home: Path | None = None, kind: str | None = None, run: Runner = _run) -> ServiceStatus:
    kind = kind or platform_kind()
    path = service_path(kind, home)
    result = ServiceStatus(
        installed=path.exists(),
        running=False,
        pid=None,
        path=path,
        command=_installed_command(kind, path) if path.exists() else [],
        log=log_path(home),
    )
    if not result.installed:
        return result
    if kind == "launchd":
        proc = run(["launchctl", "print", f"{_gui_domain()}/{LABEL}"])
        # only the service's own top-level lines (one tab); nested sections
        # such as endpoints have "state = active" lines of their own
        for line in proc.stdout.splitlines():
            if not line.startswith("\t") or line.startswith("\t\t"):
                continue
            line = line.strip()
            if line.startswith("state = "):
                result.running = line == "state = running"
            elif line.startswith("pid = ") and line[6:].isdigit():
                result.pid = int(line[6:])
    else:
        proc = run(["systemctl", "--user", "show", UNIT, "-p", "ActiveState", "-p", "MainPID"])
        values = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
        result.running = values.get("ActiveState") == "active"
        pid = values.get("MainPID", "0")
        result.pid = int(pid) if pid.isdigit() and pid != "0" else None
    return result
