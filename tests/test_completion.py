"""Shell completion: generated scripts actually complete in real shells."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from xping.cli import completion

POSIX = sys.platform != "win32"
needs_bash = pytest.mark.skipif(not (POSIX and shutil.which("bash")), reason="needs bash")
needs_zsh = pytest.mark.skipif(not (POSIX and shutil.which("zsh")), reason="needs zsh")


@pytest.fixture
def fake_env(tmp_path):
    """A HOME with two saved profiles and an `xping` on PATH running this checkout."""
    home = tmp_path / "home"
    (home / ".xping").mkdir(parents=True)
    (home / ".xping" / "profiles.json").write_text(
        json.dumps({"prod-db": {"target": "10.0.0.5"}, "staging-api": {"target": "s.example"}}),
        encoding="utf-8",
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    repo = Path(__file__).resolve().parents[1]
    shim = bindir / "xping"
    shim.write_text(
        f'#!/bin/sh\nPYTHONPATH="{repo}" exec "{sys.executable}" -m xping "$@"\n', encoding="utf-8"
    )
    shim.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    for name in ("checks.toml", "c2.json", "notes.txt"):
        (work / name).write_text("", encoding="utf-8")
    env = {**os.environ, "HOME": str(home), "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    return env, work, tmp_path


# ── the model / generated text ────────────────────────────────────────────────


def test_model_reflects_parser():
    root = completion.model()
    assert "ping" in root.subcommands and "completion" in root.subcommands
    ping = root.subcommands["ping"]
    count = next(o for o in ping.options if "--count" in o.flags)
    assert count.takes_value and "-c" in count.flags
    assert ["--json", "--csv", "--markdown", "-q", "--quiet"] in ping.exclusive
    assert ping.positionals[0].kind == "host"
    assert root.subcommands["check"].positionals[0].kind == "file"
    assert root.subcommands["profile"].subcommands["show"].positionals[0].kind == "profile"
    assert root.subcommands["profile"].subcommands["add"].positionals[0].kind == "none"
    listen = root.subcommands["listen"]
    assert next(o for o in listen.options if "--proto" in o.flags).choices == ["tcp", "udp"]


def test_zsh_script_registers_itself():
    script = completion.generate("zsh")
    assert script.startswith("#compdef xping")
    assert "compdef _xping xping" in script  # beats zsh's _hosts claiming "xping"
    assert '"${funcstack[1]}" == "_xping"' in script  # also works from fpath


def test_bash_script_is_bash32_safe():
    script = completion.generate("bash")
    for construct in ("compopt", "_init_completion", "source <(", "declare -A", "mapfile"):
        assert construct not in script
    assert "complete -F _xping xping" in script


def test_unknown_shell():
    with pytest.raises(ValueError):
        completion.generate("tcsh")


@pytest.mark.parametrize(
    ("shell", "checker"),
    [("bash", ["bash", "-n"]), ("zsh", ["zsh", "-n"]), ("fish", ["fish", "-n"])],
)
def test_scripts_parse(tmp_path, shell, checker):
    if not (POSIX and shutil.which(checker[0])):
        pytest.skip(f"{checker[0]} not installed")
    path = tmp_path / f"xping.{shell}"
    path.write_text(completion.generate(shell), encoding="utf-8")
    subprocess.run([*checker, str(path)], check=True)


# ── bash: drive the completer like readline does ──────────────────────────────

_BASH_DRIVER = textwrap.dedent(
    r"""
    source "$1"; shift
    for line in "$@"; do
      read -r -a COMP_WORDS <<< "$line"
      case "$line" in *" ") COMP_WORDS+=("") ;; esac
      COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 )); COMPREPLY=()
      _xping
      echo "${COMPREPLY[*]}"
    done
    """
)


@needs_bash
def test_bash_completes_commands_options_values_profiles_and_files(fake_env, tmp_path):
    env, work, _ = fake_env
    script = tmp_path / "xping.bash"
    script.write_text(completion.generate("bash"), encoding="utf-8")
    driver = tmp_path / "drive.sh"
    driver.write_text(_BASH_DRIVER, encoding="utf-8")
    cases = {
        "xping pi": "ping",
        "xping ping --max": "--max-loss --max-latency",
        "xping listen --proto ": "tcp udp",
        "xping propagation h -r ": "A AAAA CNAME MX NS TXT",
        "xping completion ": "bash zsh fish powershell",
        "xping profile show ": "prod-db staging-api",
        "xping ping pro": "prod-db",
        "xping ping -c ": "",  # option value: nothing to suggest
        "xping profile add ": "",  # a new name
        "xping -": "-h --help -V --version",
    }
    out = subprocess.run(
        ["bash", str(driver), str(script), *cases, "xping check "],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=work,
        check=True,
    ).stdout.splitlines()
    for (line, expected), got in zip(cases.items(), out, strict=False):
        assert got == expected, line
    assert sorted(out[-1].split()) == ["c2.json", "checks.toml"]  # notes.txt filtered out


# ── zsh: press Tab in a real interactive zsh (zpty) ───────────────────────────

_ZSH_TAB = textwrap.dedent(
    r"""
    zmodload zsh/zpty || exit 3
    zpty z zsh -f -i
    zpty -w z 'PROMPT="%% "'
    zpty -w z "$1"
    zpty -w z 'compadd () { builtin compadd -A __h "$@"; local x; for x in $__h; do print -r -- "CAND:$x"; done; builtin compadd "$@"; }'
    zpty -w z 'print -r -- "RE""ADY"'
    zpty -r z out '*READY*' >/dev/null
    zpty -w -n z "$2"$'\t'
    acc=""
    for i in {1..40}; do if zpty -r -t z chunk; then acc+=$chunk; else sleep 0.1; fi; done
    zpty -d z
    print -r -- "$acc" | tr -d '\r' | grep -a 'CAND:' | sed 's/.*CAND://' | sort -u
    """
)


@needs_zsh
@pytest.mark.parametrize(
    ("buffer", "expected"),
    [
        ("xping p", {"ping", "portscan", "profile", "propagation"}),
        ("xping listen --proto ", {"tcp", "udp"}),
        ("xping profile show ", {"prod-db", "staging-api"}),
    ],
)
def test_zsh_tab_after_sourcing(fake_env, tmp_path, buffer, expected):
    env, work, _ = fake_env
    script = tmp_path / "_xping"
    script.write_text(completion.generate("zsh"), encoding="utf-8")
    tab = tmp_path / "tab.zsh"
    tab.write_text(_ZSH_TAB, encoding="utf-8")
    # like a plain ~/.zshrc: nothing but our line — the script loads compinit itself
    setup = f"cd {work}; source {script}"
    got = subprocess.run(
        ["zsh", "-f", str(tab), setup, buffer],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    ).stdout.split()
    assert expected <= set(got), (buffer, got)


# ── install / uninstall ───────────────────────────────────────────────────────


def test_install_zsh_is_idempotent_and_preserves_rc(tmp_path, monkeypatch):
    monkeypatch.delenv("ZDOTDIR", raising=False)
    rc = tmp_path / ".zshrc"
    rc.write_text("autoload -Uz compinit && compinit\nalias ll='ls -l'\n", encoding="utf-8")
    completion.install("zsh", home=tmp_path)
    completion.install("zsh", home=tmp_path)
    text = rc.read_text(encoding="utf-8")
    assert text.count(completion._BEGIN) == 1 and "alias ll" in text
    assert text.index("compinit") < text.index(completion._BEGIN)  # appended after compinit
    script = tmp_path / ".xping" / "completions" / "_xping"
    assert script.read_text(encoding="utf-8") == completion.generate("zsh")
    completion.uninstall("zsh", home=tmp_path)
    assert completion._BEGIN not in rc.read_text(encoding="utf-8") and "alias ll" in rc.read_text(
        encoding="utf-8"
    )
    assert not script.exists()


def test_install_bash_uses_bash_profile_on_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(completion.sys, "platform", "darwin")
    completion.install("bash", home=tmp_path)
    assert completion._BEGIN in (tmp_path / ".bash_profile").read_text(encoding="utf-8")
    monkeypatch.setattr(completion.sys, "platform", "linux")
    completion.install("bash", home=tmp_path)
    assert completion._BEGIN in (tmp_path / ".bashrc").read_text(encoding="utf-8")


def test_install_fish_writes_completions_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    actions = completion.install("fish", home=tmp_path)
    assert (tmp_path / "cfg" / "fish" / "completions" / "xping.fish").exists()
    assert len(actions) == 1  # no rc file to edit for fish


def test_detect_shell(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert completion.detect_shell() == "zsh"
    monkeypatch.setenv("SHELL", "/usr/bin/tcsh")
    assert completion.detect_shell() is None
    monkeypatch.setenv("SHELL", "/usr/local/bin/pwsh")
    assert completion.detect_shell() == "powershell"
    monkeypatch.delenv("SHELL")
    monkeypatch.setattr(sys, "platform", "win32")
    assert completion.detect_shell() == "powershell"  # Windows sets no $SHELL


# ── CLI ───────────────────────────────────────────────────────────────────────


def _main(argv, monkeypatch, capsys):
    from xping.cli.main import main

    monkeypatch.setattr(sys, "argv", ["xping", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    return exc.value.code, capsys.readouterr()


def test_cli_prints_script_and_requires_shell(monkeypatch, capsys):
    code, out = _main(["completion", "bash"], monkeypatch, capsys)
    assert code == 0 and "complete -F _xping xping" in out.out
    code, _ = _main(["completion"], monkeypatch, capsys)
    assert code == 2


def test_cli_install_undetectable_shell(monkeypatch, capsys):
    monkeypatch.setenv("SHELL", "/bin/tcsh")
    code, out = _main(["completion", "--install"], monkeypatch, capsys)
    assert code == 2 and "cannot detect" in out.err


def test_cli_install_detected_shell(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ZDOTDIR", raising=False)
    monkeypatch.setattr(completion.Path, "home", lambda: tmp_path)
    code, out = _main(["completion", "--install"], monkeypatch, capsys)
    assert code == 0 and "~/.zshrc" in out.out
    assert (tmp_path / ".xping" / "completions" / "_xping").exists()


def test_profile_list_names(tmp_path, monkeypatch, capsys):
    from xping.diagnostics import profile as profile_diag

    monkeypatch.setattr(profile_diag, "STORE_DIR", tmp_path)
    monkeypatch.setattr(profile_diag, "STORE_FILE", tmp_path / "profiles.json")
    profile_diag.add("b-host", "10.0.0.2", quiet=True)
    profile_diag.add("a-host", "10.0.0.1", quiet=True)
    code, out = _main(["profile", "list", "--names"], monkeypatch, capsys)
    assert code == 0 and out.out.splitlines() == ["a-host", "b-host"]


# ── PowerShell ────────────────────────────────────────────────────────────────


def test_powershell_quoting():
    assert completion._ps("it's") == "'it''s'"
    assert completion._ps("smart \u2019quote") == "'smart ''quote'"  # PS ends strings at it too
    assert completion._ps_help("", "--x") == "'--x'"  # tooltips must not be empty


def test_powershell_script_describes_every_command():
    script = completion.generate("powershell")
    assert "Register-ArgumentCompleter -Native -CommandName xping, xping.exe" in script
    root = completion.model()
    for name in root.subcommands:
        assert f"    '{name}' = @{{" in script
    assert "pc = @(, @('bash', 'zsh', 'fish', 'powershell'))" in script  # not flattened
    assert "f = @('-c', '--count')" in script


def _ps_profiles(monkeypatch, tmp_path, found):
    monkeypatch.setattr(completion, "_powershell_profiles", lambda home: found)


def test_install_powershell_into_every_profile(tmp_path, monkeypatch):
    seven = tmp_path / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    five = tmp_path / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1"
    five.parent.mkdir(parents=True)
    five.write_bytes("\ufeffSet-Alias ll Get-ChildItem\r\n# caf\xe9\n".encode("utf-8"))
    _ps_profiles(monkeypatch, tmp_path, [seven, five])
    actions = completion.install("powershell", home=tmp_path)
    script = tmp_path / ".xping" / "completions" / "xping.ps1"
    assert script.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM for Windows PowerShell 5.1
    for profile in (seven, five):
        raw = profile.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf") and raw.count(b">>> xping completion") == 1
        assert f"if (Test-Path -LiteralPath '{script}')".encode() in raw
    assert "Set-Alias ll Get-ChildItem" in five.read_text(encoding="utf-8-sig")
    assert len(actions) == 3
    completion.install("powershell", home=tmp_path)  # idempotent
    assert seven.read_text(encoding="utf-8-sig").count(">>> xping completion") == 1
    completion.uninstall("powershell", home=tmp_path)
    assert not script.exists()
    assert "xping" not in five.read_text(encoding="utf-8-sig")
    assert "caf\xe9" in five.read_text(encoding="utf-8-sig")


def test_install_powershell_keeps_a_non_utf8_profile(tmp_path, monkeypatch):
    profile = tmp_path / "profile.ps1"
    profile.write_bytes(b"# caf\xe9 in cp1252\n")
    _ps_profiles(monkeypatch, tmp_path, [profile])
    completion.install("powershell", home=tmp_path)
    completion.uninstall("powershell", home=tmp_path)
    assert b"caf\xe9 in cp1252" in profile.read_bytes()


def test_powershell_profile_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(completion, "_ask_powershell_profile", lambda exe: tmp_path / f"{exe}.ps1")
    monkeypatch.setattr(shutil, "which", lambda exe: exe if exe == "pwsh" else None)
    assert completion._powershell_profiles(tmp_path) == [tmp_path / "pwsh.ps1"]
    monkeypatch.setattr(shutil, "which", lambda exe: None)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(sys, "platform", "linux")
    assert completion._powershell_profiles(tmp_path) == [
        tmp_path / "cfg" / "powershell" / "Microsoft.PowerShell_profile.ps1"
    ]
    monkeypatch.setattr(sys, "platform", "win32")
    assert completion._powershell_profiles(tmp_path)[0].parts[-3:] == (
        "Documents", "PowerShell", "Microsoft.PowerShell_profile.ps1"
    )


_PWSH = shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(_PWSH is None, reason="PowerShell is not installed")
def test_powershell_tab_completion(fake_env, tmp_path):
    env, _work, base = fake_env
    home = env["HOME"]
    env = {**env, "USERPROFILE": home}
    repo = Path(__file__).resolve().parents[1]
    (base / "bin" / "xping.cmd").write_text(
        f'@set PYTHONPATH={repo}\r\n@"{sys.executable}" -m xping %*\r\n', encoding="utf-8"
    )
    script = tmp_path / "xping.ps1"
    script.write_text(completion.generate("powershell"), encoding="utf-8-sig")
    cases = {
        "xping pi": ["ping"],
        "xping ping --cou": ["--count"],
        "xping completion ": ["bash", "zsh", "fish", "powershell"],
        "xping propagation example.com --type M": ["MX"],
        "xping profile ": ["add", "list", "remove", "rm", "show"],
        "xping ping ": ["prod-db", "staging-api"],
        "xping ping -c 3 st": ["staging-api"],
        "xping profile show p": ["prod-db"],
    }
    lines = json.dumps(list(cases))
    driver = textwrap.dedent(
        f"""
        . '{script}'
        $out = @{{}}
        foreach ($line in (ConvertFrom-Json @'
        {lines}
        '@)) {{
            $m = (TabExpansion2 -inputScript $line -cursorColumn $line.Length).CompletionMatches
            $out[$line] = @($m | ForEach-Object {{ $_.CompletionText }})
        }}
        $out | ConvertTo-Json -Depth 3
        """
    )
    proc = subprocess.run(
        [_PWSH, "-NoProfile", "-NonInteractive", "-Command", driver],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    for line, expected in cases.items():
        assert sorted(got[line] or []) == sorted(expected), (line, got[line])
