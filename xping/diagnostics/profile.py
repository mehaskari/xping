"""
xping.diagnostics.profile — Saved target profiles.
Lets users save frequently-used hosts under a short name, so any
host-taking command can be run as `xping ping prod-db` instead of
retyping the IP every time. Stored as plain JSON under the user's
home directory — no external dependency.
"""

import json
import re
from pathlib import Path

from xping.models.profile import ProfileEntry, ProfileListResult
from xping.render import section_header
from xping.render.errors import error
from xping.render.views import profile as profile_view

STORE_DIR = Path.home() / ".xping"
STORE_FILE = STORE_DIR / "profiles.json"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _load() -> dict:
    if not STORE_FILE.exists():
        return {}
    try:
        with open(STORE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(STORE_FILE)


def resolve_target(value: str) -> str:
    """Return the saved target for *value* if it names a profile, else *value* unchanged."""
    entry = _load().get(value)
    return entry["target"] if entry else value


def get(name: str) -> ProfileEntry | None:
    entry = _load().get(name)
    if not entry:
        return None
    return ProfileEntry(name=name, target=entry.get("target", ""),
                         port=entry.get("port"), note=entry.get("note"))


def add(name: str, target: str, port: int | None = None,
        note: str | None = None, quiet: bool = False) -> ProfileEntry | None:
    """Save *target* (and optional port/note) under *name*."""
    if not _NAME_RE.match(name):
        if not quiet:
            error(f"Invalid profile name '{name}'",
                  hint="Use letters, numbers, '.', '_', or '-' (max 64 chars).")
        return None

    data = _load()
    data[name] = {"target": target, "port": port, "note": note}
    _save(data)

    entry = ProfileEntry(name=name, target=target, port=port, note=note)
    if not quiet:
        print(section_header(f"PROFILE SAVED  {name}", "◇"))
        profile_view.print_saved(entry)
    return entry


def remove(name: str, quiet: bool = False) -> bool:
    data = _load()
    if name not in data:
        if not quiet:
            error(f"No profile named '{name}'")
        return False
    del data[name]
    _save(data)
    if not quiet:
        profile_view.print_removed(name)
    return True


def list_profiles(quiet: bool = False) -> ProfileListResult:
    data = _load()
    entries = [
        ProfileEntry(name=name, target=v.get("target", ""),
                     port=v.get("port"), note=v.get("note"))
        for name, v in sorted(data.items())
    ]
    result = ProfileListResult(profiles=entries)
    if not quiet:
        print(section_header("SAVED PROFILES", "◇"))
        profile_view.print_list(result)
    return result


def show(name: str, quiet: bool = False) -> ProfileEntry | None:
    entry = get(name)
    if not quiet:
        if entry:
            print(section_header(f"PROFILE  {name}", "◇"))
            profile_view.print_entry(entry)
        else:
            error(f"No profile named '{name}'")
    return entry
