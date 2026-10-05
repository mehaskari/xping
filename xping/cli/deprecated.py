"""Short options that meant something else in one command than everywhere
else. Until 2.0 the old spelling still works: it is rewritten to the new
option before parsing, with a warning on stderr (stdout stays clean for
--json and scripts)."""

from __future__ import annotations

import sys

# (command, old short option) -> new option
RENAMED: dict[tuple[str, str], str] = {
    ("trace", "-p"): "--probes",  # -p is --ports in portscan and sweep
    ("propagation", "-t"): "--type",  # -t is --timeout everywhere else
    ("ping", "-w"): "--watch",  # -w is --workers everywhere else
    ("wifi", "-i"): "--interface",  # -i is --interval everywhere else
}
# options that take a value, so "-p5" means "--probes=5"
_TAKES_VALUE = {"--probes", "--type", "--interface"}


def rewrite(argv: list[str], warn=None) -> list[str]:
    """Replace deprecated options in *argv* (without the program name)."""
    command = next((t for t in argv if not t.startswith("-")), None)
    if command is None or not any(cmd == command for cmd, _old in RENAMED):
        return argv
    out: list[str] = []
    seen_command = False
    for index, token in enumerate(argv):
        if token == "--":
            out += argv[index:]
            break
        if not seen_command:
            seen_command = token == command
            out.append(token)
            continue
        new = None
        for (cmd, old), replacement in RENAMED.items():
            if cmd != command:
                continue
            if token == old:
                new = replacement
            elif token.startswith(old) and replacement in _TAKES_VALUE and len(token) > 2:
                new = f"{replacement}={token[2:]}"
            if new:
                _warn(warn, command, old, replacement)
                break
        out.append(new or token)
    return out


def _warn(warn, command: str, old: str, new: str) -> None:
    message = f"xping {command}: {old} is deprecated and will be removed in 2.0; use {new}\n"
    if warn is not None:
        warn(message)
    else:
        sys.stderr.write(message)
