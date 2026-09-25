"""
xping shell completion — bash, zsh and fish.

Everything (commands, options, help text, choices, which options take a
value, mutually exclusive groups, what each positional argument is) is
read from the argparse parser, so completion can never drift from the CLI.

Install for the current shell (idempotent, re-run after upgrading):

  xping completion --install

or manually:

  zsh   source <(xping completion zsh)                      # in ~/.zshrc
  bash  eval "$(xping completion bash)"                     # ~/.bashrc / ~/.bash_profile
  fish  xping completion fish > ~/.config/fish/completions/xping.fish

Notes on the shells this targets:
- zsh ships a ``_hosts`` completion that also claims a command named
  ``xping`` (an unrelated old tool), so the zsh script always registers
  itself explicitly with ``compdef`` instead of relying on fpath order.
- macOS ships bash 3.2, where ``source <(…)`` silently does nothing and
  ``compopt``/``_init_completion`` do not exist; the bash script avoids
  all of them.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from xping import __version__
from xping.cli.parser import build_parser

# What a positional argument (by dest) should complete to
_POSITIONAL_KINDS = {
    "host": "host",
    "domain": "host",
    "ip": "host",
    "name": "host",  # propagation NAME; profile add NAME is overridden below
    "url": "url",
    "file": "file",
    "target": "none",  # CIDR / IP range
    "port": "none",
}
# Option dests whose value is a host / resolver
_HOST_OPTIONS = {"server"}


@dataclass
class Option:
    flags: list[str]
    help: str
    takes_value: bool
    choices: list[str] = field(default_factory=list)
    metavar: str = "VALUE"
    repeatable: bool = False
    value_kind: str = "none"  # "none" | "choices" | "host"


@dataclass
class Positional:
    dest: str
    help: str
    kind: str  # "host" | "profile" | "file" | "url" | "choices" | "none"
    choices: list[str] = field(default_factory=list)
    optional: bool = False


@dataclass
class Command:
    name: str
    help: str
    options: list[Option] = field(default_factory=list)
    positionals: list[Positional] = field(default_factory=list)
    exclusive: list[list[str]] = field(default_factory=list)  # groups of flags
    subcommands: dict[str, Command] = field(default_factory=dict)


def _subparsers(parser: argparse.ArgumentParser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def _describe(parser: argparse.ArgumentParser, name: str, help_text: str, path: str) -> Command:
    cmd = Command(name=name, help=help_text or "")
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction | argparse._SubParsersAction):
            continue
        if action.option_strings:
            takes_value = action.nargs != 0
            choices = [str(c) for c in action.choices] if action.choices else []
            kind = "choices" if choices else "host" if action.dest in _HOST_OPTIONS else "none"
            cmd.options.append(
                Option(
                    flags=list(action.option_strings),
                    help=action.help or "",
                    takes_value=takes_value,
                    choices=choices,
                    metavar=str(action.metavar or action.dest.upper()),
                    repeatable=isinstance(action, argparse._AppendAction),
                    value_kind=kind if takes_value else "none",
                )
            )
        else:
            choices = [str(c) for c in action.choices] if action.choices else []
            kind = "choices" if choices else _POSITIONAL_KINDS.get(action.dest, "none")
            if path in ("profile remove", "profile rm", "profile show") and action.dest == "name":
                kind = "profile"
            elif path == "profile add" and action.dest == "name":
                kind = "none"
            cmd.positionals.append(
                Positional(
                    dest=action.dest,
                    help=action.help or action.dest,
                    kind=kind,
                    choices=choices,
                    optional=action.nargs in ("?", "*"),
                )
            )
    for group in parser._mutually_exclusive_groups:
        flags = [f for a in group._group_actions for f in a.option_strings]
        if len(flags) > 1:
            cmd.exclusive.append(flags)
    sub = _subparsers(parser)
    if sub is not None:
        helps = {a.dest: a.help for a in sub._choices_actions}
        for sub_name, sub_parser in sub.choices.items():
            cmd.subcommands[sub_name] = _describe(
                sub_parser, sub_name, helps.get(sub_name, ""), f"{path} {sub_name}".strip()
            )
    return cmd


def model() -> Command:
    """The whole CLI as a tree of commands."""
    return _describe(build_parser(), "xping", "", "")


# Kept for tests and callers that want the flat view
def _from_parser() -> tuple[list[str], dict[str, list[str]]]:
    root = model()
    flags = {
        name: [f for o in cmd.options for f in o.flags if f.startswith("--")]
        for name, cmd in root.subcommands.items()
    }
    return list(root.subcommands), flags


_COMMANDS, _FLAGS = _from_parser()


# ── helpers ───────────────────────────────────────────────────────────────────


def _clean(text: str) -> str:
    """Help text safe inside zsh [...] descriptions and single quotes."""
    text = re.sub(r"\s+", " ", text.replace("%%", "%")).strip()
    return text.replace("[", "(").replace("]", ")").replace("'", "").replace(":", " -")


def _sq(text: str) -> str:
    return text.replace("'", "'\\''")


# ── zsh ───────────────────────────────────────────────────────────────────────


def _zsh_value(opt: Option) -> str:
    meta = _clean(opt.metavar.lower())
    if opt.value_kind == "choices":
        return f":{meta}:({' '.join(opt.choices)})"
    if opt.value_kind == "host":
        return f":{meta}:_hosts"
    return f":{meta}: "


def _zsh_option_specs(cmd: Command) -> list[str]:
    specs = []
    for opt in cmd.options:
        excl = set(opt.flags)
        for group in cmd.exclusive:
            if any(f in group for f in opt.flags):
                excl.update(group)
        desc = _clean(opt.help)
        value = _zsh_value(opt) if opt.takes_value else ""
        prefix = "*" if opt.repeatable else f"({' '.join(sorted(excl))})"
        for flag in opt.flags:
            suffix = ("=" if flag.startswith("--") else "+") if opt.takes_value else ""
            specs.append(f"'{prefix}{flag}{suffix}[{_sq(desc)}]{_sq(value)}'")
    return specs


def _zsh_positional_specs(cmd: Command) -> list[str]:
    specs = []
    for i, pos in enumerate(cmd.positionals, 1):
        desc = _clean(pos.help)
        action = {
            "host": "_xping_hosts",
            "profile": "_xping_profiles",
            "file": "_files -g '*.(toml|json)'",
            "url": "_urls",
            "choices": f"({' '.join(pos.choices)})",
        }.get(pos.kind, " ")
        colon = "::" if pos.optional else ":"
        specs.append(f"'{i}{colon}{_sq(desc)}:{_sq(action)}'")
    return specs


def _zsh_command_function(cmd: Command, fname: str) -> list[str]:
    lines = [f"{fname}() {{"]
    if cmd.subcommands:
        items = " ".join(f"'{_sq(n)}:{_sq(_clean(c.help))}'" for n, c in cmd.subcommands.items())
        lines += [
            "  local curcontext=$curcontext state line",
            "  _arguments -C \\",
            *[f"    {spec} \\" for spec in _zsh_option_specs(cmd)],
            "    '1: :->sub' '*:: :->rest' && return",
            "  case $state in",
            f"    sub) local -a subs; subs=({items}); _describe -t commands '{cmd.name} action' subs ;;",
            "    rest)",
            "      case $words[1] in",
        ]
        for sub_name in cmd.subcommands:
            lines.append(f"        {sub_name}) {fname}_{sub_name.replace('-', '_')} ;;")
        lines += ["      esac ;;", "  esac", "}"]
        for sub_name, sub in cmd.subcommands.items():
            lines += _zsh_command_function(sub, f"{fname}_{sub_name.replace('-', '_')}")
        return lines
    specs = _zsh_option_specs(cmd) + _zsh_positional_specs(cmd)
    if specs:
        lines.append("  _arguments -s -S \\")
        lines += [f"    {spec} \\" for spec in specs[:-1]]
        lines.append(f"    {specs[-1]}")
    else:
        lines.append("  _message 'no arguments'")
    lines.append("}")
    return lines


def _zsh_script() -> str:
    root = model()
    commands = " ".join(f"'{_sq(n)}:{_sq(_clean(c.help))}'" for n, c in root.subcommands.items())
    body = [
        "#compdef xping",
        f"# xping {__version__} zsh completion — generated by: xping completion zsh",
        "# Install: xping completion --install   (or add to ~/.zshrc: source <(xping completion zsh))",
        "",
        "_xping_profiles() {",
        "  local -a profiles",
        '  profiles=(${(f)"$(command xping profile list --names 2>/dev/null)"})',
        "  (( ${#profiles} )) && _describe -t profiles 'saved profile' profiles",
        "}",
        "",
        "_xping_hosts() {",
        "  _alternative 'profiles:saved profile:_xping_profiles' 'hosts:host:_hosts'",
        "}",
        "",
        "_xping() {",
        "  local curcontext=$curcontext state line",
        "  _arguments -C \\",
        "    '(- *)'{-V,--version}'[show version and exit]' \\",
        "    '(- *)'{-h,--help}'[show help and exit]' \\",
        "    '1: :->command' \\",
        "    '*:: :->args' && return",
        "  case $state in",
        "    command)",
        f"      local -a commands; commands=({commands})",
        "      _describe -t commands 'xping command' commands ;;",
        "    args)",
        "      case $words[1] in",
    ]
    for name in root.subcommands:
        body.append(f"        {name}) _xping_cmd_{name.replace('-', '_')} ;;")
    body += ["      esac ;;", "  esac", "}", ""]
    for name, cmd in root.subcommands.items():
        body += _zsh_command_function(cmd, f"_xping_cmd_{name.replace('-', '_')}")
        body.append("")
    body += [
        "# Loaded from fpath: complete now. Sourced: register — explicitly, because",
        "# zsh's own _hosts completion also claims the command name 'xping'.",
        'if [[ "${funcstack[1]}" == "_xping" ]]; then',
        '  _xping "$@"',
        "else",
        "  (( ${+functions[compdef]} )) || { autoload -Uz compinit && compinit -u }",
        "  compdef _xping xping",
        "fi",
    ]
    return "\n".join(body) + "\n"


# ── bash ──────────────────────────────────────────────────────────────────────


def _bash_case(cmd: Command, word_var: str = "cmd") -> list[str]:
    """case-arms for one command level, used by the bash completer."""
    lines = []
    for name, sub in cmd.subcommands.items():
        opts = " ".join(f for o in sub.options for f in o.flags)
        value_opts = [o for o in sub.options if o.takes_value]
        kinds = " ".join(p.kind for p in sub.positionals) or "-"
        lines.append(f"    {name})")
        lines.append(f"      opts='{opts}'")
        lines.append(f"      kinds='{kinds}'")
        # value options: what to offer after them
        cases = []
        for o in value_opts:
            pattern = "|".join(o.flags)
            if o.value_kind == "choices":
                cases.append(
                    f"        {pattern}) _xping_reply '{' '.join(o.choices)}'; return 0 ;;"
                )
            elif o.value_kind == "host":
                cases.append(f"        {pattern}) _xping_hosts; return 0 ;;")
            else:
                cases.append(f"        {pattern}) COMPREPLY=(); return 0 ;;")
        if cases:
            lines.append('      case "$prev" in')
            lines += cases
            lines.append("      esac")
        valued = " ".join(f for o in value_opts for f in o.flags)
        lines.append(f"      valued='{valued}'")
        choices = [p for p in sub.positionals if p.kind == "choices"]
        if choices:
            lines.append(f"      pchoices='{' '.join(choices[0].choices)}'")
        if sub.subcommands:
            subs = " ".join(sub.subcommands)
            lines.append(f"      subs='{subs}'")
            for sub_name, subsub in sub.subcommands.items():
                sopts = " ".join(f for o in subsub.options for f in o.flags)
                skinds = " ".join(p.kind for p in subsub.positionals) or "-"
                svalued = " ".join(f for o in subsub.options if o.takes_value for f in o.flags)
                key = sub_name.replace("-", "_")
                lines.append(f"      sub_opts_{key}='{sopts}'")
                lines.append(f"      sub_kinds_{key}='{skinds}'")
                lines.append(f"      sub_valued_{key}='{svalued}'")
        lines.append("      ;;")
    return lines


def _bash_script() -> str:
    root = model()
    commands = " ".join(root.subcommands)
    arms = "\n".join(_bash_case(root))
    return f"""\
# xping {__version__} bash completion — generated by: xping completion bash
# Install: xping completion --install   (or add: eval "$(xping completion bash)")
# Works with bash 3.2 (macOS) and later; bash-completion is not required.

_xping_reply() {{
    COMPREPLY=( $(compgen -W "$1" -- "$cur") )
}}

_xping_hosts() {{
    local profiles
    profiles=$(command xping profile list --names 2>/dev/null)
    COMPREPLY=( $( {{ compgen -W "$profiles" -- "$cur"; compgen -A hostname -- "$cur"; }} | awk '!seen[$0]++' ) )
}}

_xping_files() {{
    local IFS=$'\\n' f
    COMPREPLY=()
    for f in $(compgen -f -- "$cur"); do
        if [ -d "$f" ]; then COMPREPLY+=( "$f/" )
        else case "$f" in *.toml|*.json) COMPREPLY+=( "$f" ) ;; esac
        fi
    done
}}

_xping_positional() {{
    case "$1" in
        host) _xping_hosts ;;
        profile) COMPREPLY=( $(compgen -W "$(command xping profile list --names 2>/dev/null)" -- "$cur") ) ;;
        file) _xping_files ;;
        choices) _xping_reply "$pchoices" ;;
        *) COMPREPLY=() ;;
    esac
}}

_xping() {{
    local cur prev cmd="" cmd_idx=0 i w
    local opts="" kinds="-" valued="" subs="" pchoices=""
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    COMPREPLY=()

    for (( i=1; i < COMP_CWORD; i++ )); do
        case "${{COMP_WORDS[i]}}" in
            -*) ;;
            *) cmd="${{COMP_WORDS[i]}}"; cmd_idx=$i; break ;;
        esac
    done

    if [ -z "$cmd" ]; then
        case "$cur" in
            -*) _xping_reply "-h --help -V --version" ;;
            *) _xping_reply "{commands}" ;;
        esac
        return 0
    fi

    case "$cmd" in
{arms}
        *) return 0 ;;
    esac

    # nested subcommand (profile add/remove/…)
    if [ -n "$subs" ]; then
        local sub="" sub_idx=0
        for (( i=cmd_idx+1; i < COMP_CWORD; i++ )); do
            case "${{COMP_WORDS[i]}}" in -*) ;; *) sub="${{COMP_WORDS[i]}}"; sub_idx=$i; break ;; esac
        done
        if [ -z "$sub" ]; then
            case "$cur" in -*) _xping_reply "$opts" ;; *) _xping_reply "$subs" ;; esac
            return 0
        fi
        local var="sub_opts_${{sub//-/_}}"; opts="${{!var}}"
        var="sub_kinds_${{sub//-/_}}"; kinds="${{!var}}"
        var="sub_valued_${{sub//-/_}}"; valued="${{!var}}"
        cmd_idx=$sub_idx
        case " $valued " in *" $prev "*) COMPREPLY=(); return 0 ;; esac
    fi

    case "$cur" in
        -*) _xping_reply "$opts"; return 0 ;;
    esac

    # which positional is being completed? (skip options and their values)
    local n=0 skip=0
    for (( i=cmd_idx+1; i < COMP_CWORD; i++ )); do
        w="${{COMP_WORDS[i]}}"
        if [ $skip -eq 1 ]; then skip=0; continue; fi
        case "$w" in
            --*=*) ;;
            -*) case " $valued " in *" $w "*) skip=1 ;; esac ;;
            *) n=$((n+1)) ;;
        esac
    done
    local k=0 kind="none"
    for w in $kinds; do
        if [ $k -eq $n ]; then kind="$w"; break; fi
        k=$((k+1))
    done
    _xping_positional "$kind"
    return 0
}}

complete -F _xping xping
"""


# ── fish ──────────────────────────────────────────────────────────────────────


def _fish_script() -> str:
    root = model()
    lines = [
        f"# xping {__version__} fish completion — generated by: xping completion fish",
        "# Install: xping completion --install",
        "#   (or: xping completion fish > ~/.config/fish/completions/xping.fish)",
        "",
        "function __xping_profiles",
        "    command xping profile list --names 2>/dev/null",
        "end",
        "",
        "function __xping_check_files --description 'directories and .toml/.json files'",
        "    for f in (commandline -ct)*",
        "        if test -d $f",
        "            echo $f/",
        "        else if string match -qr '\\.(toml|json)$' -- $f",
        "            echo $f",
        "        end",
        "    end",
        "end",
        "",
        "complete -c xping -f",
        "complete -c xping -n __fish_use_subcommand -s V -l version -d 'Show version and exit'",
        "complete -c xping -n __fish_use_subcommand -s h -l help -d 'Show help and exit'",
    ]
    for name, cmd in root.subcommands.items():
        lines.append(
            f"complete -c xping -n __fish_use_subcommand -a {name} -d '{_sq(_clean(cmd.help))}'"
        )
    lines.append("")
    for name, cmd in root.subcommands.items():
        cond = f"__fish_seen_subcommand_from {name}"
        for opt in cmd.options:
            parts = [f"complete -c xping -n '{cond}'"]
            for flag in opt.flags:
                parts.append(f"-l {flag[2:]}" if flag.startswith("--") else f"-s {flag[1:]}")
            if opt.takes_value:
                parts.append("-x")
                if opt.value_kind == "choices":
                    parts.append(f"-a '{' '.join(opt.choices)}'")
                elif opt.value_kind == "host":
                    parts.append("-a '(__fish_print_hostnames)'")
            parts.append(f"-d '{_sq(_clean(opt.help))}'")
            lines.append(" ".join(parts))
        kinds = {p.kind for p in cmd.positionals}
        if "host" in kinds:
            lines.append(
                f"complete -c xping -n '{cond}' -a '(__xping_profiles) (__fish_print_hostnames)'"
            )
        if "file" in kinds:
            lines.append(f"complete -c xping -n '{cond}' -a '(__xping_check_files)'")
        for pos in cmd.positionals:
            if pos.kind == "choices":
                lines.append(f"complete -c xping -n '{cond}' -a '{' '.join(pos.choices)}'")
        if cmd.subcommands:
            subs = " ".join(cmd.subcommands)
            lines.append(
                f"complete -c xping -n '{cond}; and not __fish_seen_subcommand_from {subs}' "
                f"-a '{subs}'"
            )
            for sub_name, sub in cmd.subcommands.items():
                sub_cond = f"{cond}; and __fish_seen_subcommand_from {sub_name}"
                for opt in sub.options:
                    flag_parts = " ".join(
                        f"-l {f[2:]}" if f.startswith("--") else f"-s {f[1:]}" for f in opt.flags
                    )
                    x = " -x" if opt.takes_value else ""
                    lines.append(
                        f"complete -c xping -n '{sub_cond}' {flag_parts}{x} -d '{_sq(_clean(opt.help))}'"
                    )
                if any(p.kind == "profile" for p in sub.positionals):
                    lines.append(f"complete -c xping -n '{sub_cond}' -a '(__xping_profiles)'")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate(shell: str) -> str:
    if shell == "bash":
        return _bash_script()
    if shell == "zsh":
        return _zsh_script()
    if shell == "fish":
        return _fish_script()
    raise ValueError(f"Unknown shell '{shell}'. Choose: bash, zsh, fish")


# ── install / uninstall ───────────────────────────────────────────────────────

_BEGIN = "# >>> xping completion >>>"
_END = "# <<< xping completion <<<"


def detect_shell() -> str | None:
    name = Path(os.environ.get("SHELL", "")).name
    return name if name in ("bash", "zsh", "fish") else None


def _rc_file(shell: str, home: Path) -> Path | None:
    if shell == "zsh":
        return Path(os.environ.get("ZDOTDIR", home)) / ".zshrc"
    if shell == "bash":
        # macOS Terminal opens login shells, which read ~/.bash_profile, not ~/.bashrc
        return home / (".bash_profile" if sys.platform == "darwin" else ".bashrc")
    return None


def _script_path(shell: str, home: Path) -> Path:
    if shell == "fish":
        config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        return config / "fish" / "completions" / "xping.fish"
    return home / ".xping" / "completions" / ("_xping" if shell == "zsh" else "xping.bash")


def _tilde(path: Path, home: Path) -> str:
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def _strip_block(text: str) -> str:
    return re.sub(rf"\n?{re.escape(_BEGIN)}.*?{re.escape(_END)}\n?", "\n", text, flags=re.S)


def install(shell: str, home: Path | None = None) -> list[str]:
    """Write the completion script and hook it into the shell's rc file.
    Idempotent: re-running replaces the script and the rc block. Returns a
    list of human-readable actions taken."""
    home = home or Path.home()
    actions = []
    script = _script_path(shell, home)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(generate(shell), encoding="utf-8")
    actions.append(f"wrote {_tilde(script, home)}")
    rc = _rc_file(shell, home)
    if rc is not None:
        source = f'source "{script}"' if shell == "zsh" else f'[ -f "{script}" ] && . "{script}"'
        block = f"{_BEGIN}\n{source}\n{_END}\n"
        existing = rc.read_text(encoding="utf-8") if rc.exists() else ""
        cleaned = _strip_block(existing).rstrip("\n")
        rc.write_text((cleaned + "\n\n" if cleaned else "") + block, encoding="utf-8")
        verb = "updated" if _BEGIN in existing else "added a block to"
        actions.append(f"{verb} {_tilde(rc, home)}")
    return actions


def uninstall(shell: str, home: Path | None = None) -> list[str]:
    home = home or Path.home()
    actions = []
    script = _script_path(shell, home)
    if script.exists():
        script.unlink()
        actions.append(f"removed {_tilde(script, home)}")
    rc = _rc_file(shell, home)
    if rc is not None and rc.exists():
        text = rc.read_text(encoding="utf-8")
        if _BEGIN in text:
            rc.write_text(_strip_block(text).rstrip("\n") + "\n", encoding="utf-8")
            actions.append(f"removed the xping block from {_tilde(rc, home)}")
    return actions
