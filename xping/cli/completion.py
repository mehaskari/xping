"""
xping shell completion generator.
Supports bash, zsh, and fish.

Usage:
  xping completion bash >> ~/.bashrc
  xping completion zsh  >> ~/.zshrc
  xping completion fish > ~/.config/fish/completions/xping.fish
"""

from __future__ import annotations

_COMMANDS = [
    "ping", "trace", "lookup", "tcp", "portscan", "sweep", "ipscan",
    "all", "rdns", "dnscheck", "tls", "http", "whois", "health",
    "mtr", "mtu", "profile", "speedtest", "listen", "osdetect",
    "deps", "about",
]

_FLAGS: dict[str, list[str]] = {
    "ping":      ["--count", "--timeout", "--interval", "--watch", "--alarm",
                  "--json", "--csv", "--markdown"],
    "trace":     ["--max-hops", "--timeout", "--probes", "--json", "--csv", "--markdown"],
    "lookup":    ["--full", "--server", "--json", "--csv", "--markdown"],
    "tcp":       ["--count", "--timeout", "--interval", "--json", "--csv", "--markdown"],
    "portscan":  ["--ports", "--timeout", "--workers", "--banners", "--json", "--csv", "--markdown"],  # noqa: E501
    "sweep":     ["--ports", "--timeout", "--workers", "--limit", "--json", "--csv", "--markdown"],
    "ipscan":    ["--timeout", "--workers", "--limit", "--json", "--csv", "--markdown"],
    "all":       ["--json", "--csv", "--markdown"],
    "rdns":      ["--json", "--csv", "--markdown"],
    "dnscheck":  ["--json", "--csv", "--markdown"],
    "tls":       ["--port", "--timeout", "--json", "--csv", "--markdown"],
    "http":      ["--timeout", "--json", "--csv", "--markdown"],
    "whois":     ["--json", "--csv", "--markdown"],
    "health":    ["--count", "--timeout", "--json", "--csv", "--markdown"],
    "mtr":       ["--cycles", "--max-hops", "--timeout", "--interval", "--json", "--csv", "--markdown"],  # noqa: E501
    "mtu":       ["--max-mtu", "--timeout", "--json", "--csv", "--markdown"],
    "profile":   [],
    "speedtest": [],
    "listen":    ["--proto", "--json", "--csv", "--markdown"],
    "osdetect":  [],
    "deps":      [],
    "about":     [],
}

_PROFILE_SUBCOMMANDS = ["add", "remove", "list", "show"]


def _bash_script() -> str:
    cmds = " ".join(_COMMANDS)
    flags_block = ""
    for cmd, flags in _FLAGS.items():
        if flags:
            flags_str = " ".join(flags)
            flags_block += f"            {cmd}) opts='{flags_str}' ;;\n"

    return f"""\
# xping bash completion
# Add to ~/.bashrc:  source <(xping completion bash)

_xping_complete() {{
    local cur prev words cword
    _init_completion 2>/dev/null || {{
        COMPREPLY=()
        cur="${{COMP_WORDS[COMP_CWORD]}}"
        prev="${{COMP_WORDS[COMP_CWORD-1]}}"
        words=("${{COMP_WORDS[@]}}")
        cword=$COMP_CWORD
    }}

    local commands="{cmds}"

    # First word after xping — complete subcommands
    if [[ $cword -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
        return 0
    fi

    local cmd="${{words[1]}}"

    # profile subcommands
    if [[ "$cmd" == "profile" && $cword -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "add remove list show" -- "$cur") )
        return 0
    fi

    # listen --proto values
    if [[ "$prev" == "--proto" ]]; then
        COMPREPLY=( $(compgen -W "tcp udp" -- "$cur") )
        return 0
    fi

    # flags per command
    local opts=""
    case "$cmd" in
{flags_block}\
    esac

    if [[ -n "$opts" ]]; then
        COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    fi
    return 0
}}

complete -F _xping_complete xping
"""


def _zsh_script() -> str:
    cmds_desc = "\n".join(
        f"    '{cmd}:xping {cmd}'" for cmd in _COMMANDS
    )
    flags_cases = ""
    for cmd, flags in _FLAGS.items():
        if not flags:
            continue
        args_str = " ".join(f"'({f}){f}[{f}]'" for f in flags)
        flags_cases += f"        ({cmd})\n            _arguments {args_str}\n            ;;\n"

    return f"""\
#compdef xping
# xping zsh completion
# Add to ~/.zshrc:  source <(xping completion zsh)
# Or:               xping completion zsh > "${{fpath[1]}}/_xping"

_xping() {{
    local -a commands
    commands=(
{cmds_desc}
    )

    local -a profile_subcommands
    profile_subcommands=('add:save a profile' 'remove:delete a profile' 'list:list all' 'show:show one')

    if (( CURRENT == 2 )); then
        _describe 'xping commands' commands
        return
    fi

    case "${{words[2]}}" in
        profile)
            if (( CURRENT == 3 )); then
                _describe 'profile actions' profile_subcommands
            fi
            ;;
{flags_cases}\
    esac
}}

_xping "$@"
"""


def _fish_script() -> str:
    lines = ["# xping fish completion",
             "# Save to:  ~/.config/fish/completions/xping.fish",
             "# Or run:   xping completion fish > ~/.config/fish/completions/xping.fish",
             ""]
    for cmd in _COMMANDS:
        lines.append(f"complete -c xping -f -n '__fish_use_subcommand' "
                     f"-a {cmd} -d 'xping {cmd}'")
    lines.append("")
    for cmd, flags in _FLAGS.items():
        for flag in flags:
            flag_name = flag.lstrip("-")
            lines.append(f"complete -c xping -n '__fish_seen_subcommand_from {cmd}' "
                         f"-l {flag_name}")
    lines.append("")
    lines.append("# profile subcommands")
    for sub in _PROFILE_SUBCOMMANDS:
        lines.append(f"complete -c xping -n '__fish_seen_subcommand_from profile' "
                     f"-a {sub} -d 'profile {sub}'")
    return "\n".join(lines) + "\n"


def generate(shell: str) -> str:
    if shell == "bash":
        return _bash_script()
    if shell == "zsh":
        return _zsh_script()
    if shell == "fish":
        return _fish_script()
    raise ValueError(f"Unknown shell '{shell}'. Choose: bash, zsh, fish")
