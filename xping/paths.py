"""
xping.paths — where xping keeps its files, kept private to the user.

``~/.xping`` holds check files, personal defaults, history, monitor state and
the monitor's log, and those can name internal hosts or hold a webhook URL.
``private_dir()`` creates a directory owner-only (0700) and tightens one that
xping created earlier with the default permissions, as well as the
``.xping`` directory above it, so other users of the machine cannot read it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DIR_NAME = ".xping"


def _tighten(path: Path) -> None:
    try:
        info = path.stat()
        if info.st_uid == os.getuid() and info.st_mode & 0o077:
            path.chmod(0o700)
    except OSError:
        pass  # a directory we cannot inspect or change is left as it is


def private_dir(path: Path) -> Path:
    """``mkdir -p`` *path*, owner-only; returns *path*."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform == "win32":  # NTFS permissions are not mode bits
        return path
    _tighten(path)
    # up to ~/.xping: the directories in between hold the same kind of data
    for parent in path.parents:
        if parent.name == DIR_NAME:
            for directory in (path, *path.parents):
                _tighten(directory)
                if directory == parent:
                    break
            break
    return path
