"""
xping.cli.config — personal defaults from ~/.xping/config.toml.

    [defaults]          # every command that has the option
    timeout = 3
    ipv4 = true

    [ping]              # one command
    count = 10

    [lookup]
    doh = "cloudflare"

Keys are the long option names (``max-latency`` or ``max_latency``). The
file only changes defaults: anything on the command line wins. When the
command line uses one option of a mutually exclusive pair (``-6`` against
``ipv4 = true`` in the file, ``--server`` against ``doh``), the file's
value for the other one is dropped.

``XPING_CONFIG`` points at another file; ``XPING_CONFIG=none`` ignores the
config entirely. TOML needs Python 3.11+ (``tomllib``).
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path.home() / ".xping" / "config.toml"
# Section names that are not commands
_GLOBAL = "defaults"
# Options that make no sense as a stored default
_NOT_ALLOWED = {"help", "version", "install", "uninstall", "example", "names"}

EXAMPLE = """\
# xping personal defaults — save as ~/.xping/config.toml
# Keys are long option names; anything on the command line still wins.
# Check what is active with:  xping config

[defaults]            # applies to every command that has the option
# timeout = 3
# ipv4 = true         # or: ipv6 = true

[ping]
count = 10
interval = 0.2

[trace]
# asn = true          # show each hop's network operator
# tcp = true          # TCP SYN probes instead of ICMP

[lookup]
# server = "1.1.1.1"
# doh = "cloudflare"  # or google, quad9, an https:// URL

[http]
# timeout = 10

[ntp]
# server = "time.cloudflare.com"   # positional arguments can be defaulted too
"""


class ConfigError(ValueError):
    """The config file is unreadable or has an invalid entry."""


@dataclass
class Config:
    path: Path | None  # None when disabled or not found
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    disabled: bool = False

    @property
    def loaded(self) -> bool:
        return self.path is not None


def config_path() -> Path | None:
    value = os.environ.get("XPING_CONFIG")
    if value is not None:
        return None if value.strip().lower() in ("", "none", "off", "0") else Path(value)
    return DEFAULT_PATH


def load() -> Config:
    path = config_path()
    if path is None:
        return Config(path=None, disabled=True)
    try:
        if not path.is_file():
            return Config(path=None)
        raw = path.read_bytes()
    except OSError as exc:  # unreadable home directory must not break xping
        if os.environ.get("XPING_CONFIG"):
            raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from exc
        return Config(path=None)
    try:
        import tomllib
    except ModuleNotFoundError as exc:  # Python 3.10
        raise ConfigError(f"{path}: TOML config files need Python 3.11+") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: invalid TOML ({exc})") from exc
    sections = {}
    for name, values in data.items():
        if not isinstance(values, dict):
            raise ConfigError(f"{path}: '{name}' must be a [section] (e.g. [defaults] or [ping])")
        sections[name.lower()] = {k.replace("-", "_"): v for k, v in values.items()}
    return Config(path=path, sections=sections)


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


def _convert(action: argparse.Action, value: Any, where: str) -> Any:
    """Validate a config value with the option's own type/choices."""
    if action.nargs == 0:  # store_true flags
        if not isinstance(value, bool):
            raise ConfigError(f"{where}: must be true or false")
        return value
    if isinstance(action, argparse._AppendAction):
        values = value if isinstance(value, list) else [value]
        return [_convert_one(action, v, where) for v in values]
    return _convert_one(action, value, where)


def _convert_one(action: argparse.Action, value: Any, where: str) -> Any:
    if isinstance(value, bool | dict | list):
        raise ConfigError(f"{where}: expected a single value, got {value!r}")
    try:
        converted = action.type(str(value)) if action.type else value
    except argparse.ArgumentTypeError as exc:
        raise ConfigError(f"{where}: {exc}") from exc
    except (TypeError, ValueError) as exc:
        kind = getattr(action.type, "__name__", "value")
        raise ConfigError(f"{where}: {value!r} is not a valid {kind}") from exc
    if action.choices is not None and converted not in action.choices:
        choices = ", ".join(map(str, action.choices))
        raise ConfigError(f"{where}: must be one of {choices}")
    return converted


def apply(parser: argparse.ArgumentParser, config: Config) -> None:
    """Install the config values as parser defaults. Unknown sections or
    keys are errors, so a typo never silently does nothing."""
    if not config.sections:
        return
    try:
        _apply(parser, config)
    except ConfigError as exc:
        message = str(exc)
        if config.path is not None and not message.startswith(str(config.path)):
            message = f"{config.path}: {message}"
        raise ConfigError(message) from None


def _apply(parser: argparse.ArgumentParser, config: Config) -> None:
    commands = _subparsers(parser)
    for section in config.sections:
        if section != _GLOBAL and section not in commands:
            raise ConfigError(f"{config.path}: unknown section [{section}]")
    global_values = config.sections.get(_GLOBAL, {})
    used_globals: set[str] = set()
    for name, sub in commands.items():
        actions = {
            a.dest: a
            for a in sub._actions
            if a.dest not in _NOT_ALLOWED and (a.option_strings or a.nargs in ("?", "*"))
        }
        defaults: dict[str, Any] = {}
        for key, value in global_values.items():
            if key in actions:
                defaults[key] = _convert(actions[key], value, f"[{_GLOBAL}] {key}")
                used_globals.add(key)
        for key, value in config.sections.get(name, {}).items():
            if key not in actions:
                raise ConfigError(f"{config.path}: [{name}] has no option '{key}'")
            defaults[key] = _convert(actions[key], value, f"[{name}] {key}")
        if defaults:
            sub.set_defaults(**defaults)
    unused = sorted(set(global_values) - used_globals)
    if unused:
        raise ConfigError(
            f"{config.path}: [{_GLOBAL}] no command has option(s): {', '.join(unused)}"
        )


def resolve_conflicts(
    fresh: argparse.ArgumentParser, args: argparse.Namespace, argv: list[str]
) -> None:
    """Command line beats config inside mutually exclusive groups: when one
    member was given explicitly, reset the others to their built-in default.

    *fresh* is a parser without config applied (set_defaults() rewrites the
    actions' defaults, so the built-in ones must come from a new parser)."""
    command = getattr(args, "command", None)
    if not command:
        return
    sub = _subparsers(fresh).get(command)
    if sub is None:
        return
    given = set()
    for token in argv:
        flag = token.split("=", 1)[0]
        for action in sub._actions:
            if flag in action.option_strings:
                given.add(action.dest)
    for group in sub._mutually_exclusive_groups:
        members = group._group_actions
        if not any(a.dest in given for a in members):
            continue
        for action in members:
            if action.dest not in given:
                setattr(args, action.dest, action.default)


def builtin_defaults(parser_factory) -> dict[str, dict[str, Any]]:
    """Per-command defaults of a fresh parser (for `xping config`)."""
    return {
        name: {a.dest: a.default for a in sub._actions if a.dest not in _NOT_ALLOWED}
        for name, sub in _subparsers(parser_factory()).items()
    }
