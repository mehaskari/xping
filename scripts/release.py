#!/usr/bin/env python3
"""Release xping in one command: ``python3 scripts/release.py 1.5.3``.

Does what RELEASE.md describes, in order, and stops at the first problem:

1. checks: on an up-to-date, clean ``main``; the version is new (also on
   PyPI); ``docs/changelog.md`` has an ``[Unreleased]`` section
2. bumps the version in every versioned file, dates the man page and the
   changelog, and writes a ``debian/changelog`` entry from the changelog
3. runs the local checks (pytest, ruff, mypy) unless ``--skip-checks``
4. opens the release pull request with auto-merge and waits until it merges
5. tags the merge commit ``vX.Y.Z`` and pushes the tag (PyPI, GitHub
   Release, Launchpad PPA), then asks the Homebrew tap to follow at once

It runs ``git`` and ``gh`` as you, so CI runs on the pull request and the
tag starts the release workflows as usual. ``--dry-run`` shows the
changes without touching anything.
"""

from __future__ import annotations

import argparse
import email.utils
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "mehaskari/xping"
TAP = "mehaskari/homebrew-tap"
MAINTAINER = "Mehdi Askari <iorganamis@gmail.com>"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# file -> (pattern with one group around the version, replacement template)
VERSIONED = {
    "pyproject.toml": (r'(?m)^version = "([^"]+)"', 'version = "{v}"'),
    "xping/__init__.py": (r'(?m)^__version__ = "([^"]+)"', '__version__ = "{v}"'),
    "setup.cfg": (r"(?m)^version = (\S+)$", "version = {v}"),
    "snap/snapcraft.yaml": (r"(?m)^version: '([^']+)'$", "version: '{v}'"),
}


class ReleaseError(RuntimeError):
    pass


# ── pure text transformations (unit-tested) ─────────────────────────────────


def current_version(pyproject: str) -> str:
    found = re.search(VERSIONED["pyproject.toml"][0], pyproject)
    if not found:
        raise ReleaseError("no version in pyproject.toml")
    return found.group(1)


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def bump_text(name: str, text: str, version: str) -> str:
    pattern, template = VERSIONED[name]
    new, count = re.subn(pattern, template.format(v=version), text, count=1)
    if count != 1:
        raise ReleaseError(f"no version found in {name}")
    return new


def bump_man(text: str, version: str, day: str) -> str:
    new, count = re.subn(
        r'(?m)^\.TH XPING 1 "[^"]*" "xping [^"]*"',
        f'.TH XPING 1 "{day}" "xping {version}"',
        text,
        count=1,
    )
    if count != 1:
        raise ReleaseError("no .TH line in man/xping.1")
    return new


def unreleased_notes(changelog: str) -> list[str]:
    """Every top-level bullet of the [Unreleased] section, as one line each
    (continuation lines joined, Markdown emphasis and code marks removed)."""
    match = re.search(r"(?ms)^## \[Unreleased\]\n(.*?)(?=^## \[)", changelog)
    if not match:
        raise ReleaseError("docs/changelog.md has no '## [Unreleased]' section")
    notes: list[str] = []
    for line in match.group(1).splitlines():
        if line.startswith("- "):
            notes.append(line[2:].strip())
        elif notes and line.startswith("  ") and line.strip():
            notes[-1] += " " + line.strip().removeprefix("- ")
    notes = [re.sub(r"[*`]", "", n) for n in notes]
    if not notes:
        raise ReleaseError("the [Unreleased] section of docs/changelog.md is empty")
    return notes


def date_changelog(changelog: str, version: str, day: str) -> str:
    return changelog.replace("## [Unreleased]", f"## [{version}] - {day}", 1)


def debian_entry(version: str, notes: list[str], when: str) -> str:
    lines = [f"xping ({version}-1) noble; urgency=medium", ""]
    for note in notes:
        words, line = note.split(), "  *"
        for word in words:
            if len(line) + 1 + len(word) > 72:
                lines.append(line)
                line = "   "
            line += " " + word
        lines.append(line)
    lines += ["", f" -- {MAINTAINER}  {when}", "", ""]
    return "\n".join(lines)


# ── steps ────────────────────────────────────────────────────────────────────


def sh(*cmd: str, capture: bool = True, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=capture, text=True, check=False)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() if capture else ""
        raise ReleaseError(f"{' '.join(cmd)} failed" + (f":\n{detail}" if detail else ""))
    return (proc.stdout or "").strip() if capture else ""


def say(text: str) -> None:
    print(f"==> {text}", flush=True)


def preflight(version: str, strict: bool = True) -> str:
    """Refuse to release from anything but a clean, current main (a dry run
    only warns)."""

    def problem(text: str) -> None:
        if strict:
            raise ReleaseError(text)
        print(f"  (dry run) warning: {text}", flush=True)

    if not VERSION_RE.match(version):
        raise ReleaseError(f"'{version}' is not X.Y.Z")
    old = current_version((ROOT / "pyproject.toml").read_text())
    if _key(version) <= _key(old):
        raise ReleaseError(f"{version} is not newer than the current {old}")
    if sh("git", "branch", "--show-current") != "main":
        problem("switch to main first")
    if sh("git", "status", "--porcelain"):
        problem("the working tree has uncommitted changes")
    sh("git", "fetch", "-q", "origin", "main")
    if sh("git", "rev-parse", "HEAD") != sh("git", "rev-parse", "origin/main"):
        problem("HEAD is not origin/main (git pull)")
    try:
        urllib.request.urlopen(f"https://pypi.org/pypi/xping/{version}/json", timeout=15)
        raise ReleaseError(f"{version} already exists on PyPI")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise ReleaseError(f"PyPI check failed: HTTP {exc.code}") from exc
    unreleased_notes((ROOT / "docs/changelog.md").read_text())
    return old


def bump(version: str, dry_run: bool) -> list[str]:
    day = date.today().isoformat()
    changed = {}
    for name in VERSIONED:
        changed[name] = bump_text(name, (ROOT / name).read_text(), version)
    changed["man/xping.1"] = bump_man((ROOT / "man/xping.1").read_text(), version, day)
    changelog = (ROOT / "docs/changelog.md").read_text()
    notes = unreleased_notes(changelog)
    changed["docs/changelog.md"] = date_changelog(changelog, version, day)
    when = email.utils.formatdate(time.time()).replace("-0000", "+0000")
    debian = (ROOT / "debian/changelog").read_text()
    changed["debian/changelog"] = debian_entry(version, notes, when) + debian
    if dry_run:
        for name, text in changed.items():
            old = (ROOT / name).read_text()
            print(f"  {name}: {'changed' if text != old else 'unchanged'}")
        print("\n" + debian_entry(version, notes, when))
    else:
        for name, text in changed.items():
            (ROOT / name).write_text(text)
    return list(changed)


def run_checks() -> None:
    say("local checks: pytest, ruff, mypy")
    sh(sys.executable, "-m", "pytest", "-q", capture=False)
    sh("ruff", "check", "xping/", "--config", "ruff.toml", capture=False)
    sh("ruff", "format", "--check", "xping/", "--line-length", "100", capture=False)
    sh(sys.executable, "-m", "mypy", capture=False)


def wait_for_merge(pr: str, timeout: float = 45 * 60) -> str:
    say(f"waiting for {pr} to pass CI and merge (auto-merge)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = sh(
            "gh",
            "pr",
            "view",
            pr,
            "--json",
            "state,mergeCommit",
            "-q",
            '"\\(.state) \\(.mergeCommit.oid // "")"',
        )
        if state.startswith("MERGED "):
            return state.split()[1]
        if state.startswith("CLOSED"):
            raise ReleaseError(f"{pr} was closed without merging")
        failed = sh(
            "gh",
            "pr",
            "view",
            pr,
            "--json",
            "statusCheckRollup",
            "-q",
            '[.statusCheckRollup[] | select(.conclusion=="FAILURE") | .name] | join(", ")',
        )
        if failed:
            raise ReleaseError(f"CI failed on {pr}: {failed}")
        time.sleep(20)
    raise ReleaseError(f"{pr} did not merge within {timeout / 60:.0f} minutes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release xping (see RELEASE.md).")
    parser.add_argument("version", help="the new version, X.Y.Z")
    parser.add_argument("--dry-run", action="store_true", help="show the changes, touch nothing")
    parser.add_argument("--skip-checks", action="store_true", help="do not run pytest/ruff/mypy")
    args = parser.parse_args(argv)
    version = args.version.removeprefix("v")
    try:
        old = preflight(version, strict=not args.dry_run)
        say(f"{old} -> {version}")
        files = bump(version, args.dry_run)
        if args.dry_run:
            return 0
        if not args.skip_checks:
            run_checks()
        branch = f"release/{version}"
        sh("git", "checkout", "-q", "-b", branch)
        sh("git", "add", *files)
        sh("git", "commit", "-q", "-m", f"chore: release v{version}")
        sh("git", "push", "-q", "-u", "origin", branch)
        pr = sh(
            "gh",
            "pr",
            "create",
            "--title",
            f"chore: release v{version}",
            "--body",
            f"Release {version}. See docs/changelog.md.\n\nOpened by scripts/release.py.",
        )
        sh("gh", "pr", "merge", "--auto", "--merge", pr)
        merge = wait_for_merge(pr)
        sh("git", "checkout", "-q", "main")
        sh("git", "pull", "-q", "--ff-only")
        if sh("git", "rev-parse", "HEAD") != merge:
            raise ReleaseError(f"main is not at the merge commit {merge[:7]}; tag it by hand")
        sh("git", "tag", "-a", f"v{version}", "-m", f"Release v{version}")
        sh("git", "push", "-q", "origin", f"v{version}")
        say(f"tagged v{version}: PyPI, GitHub Release and the PPA are being published")
        sh("git", "branch", "-q", "-D", branch, check=False)
        say("asking the Homebrew tap to follow (it builds and tests on macOS)")
        sh("gh", "workflow", "run", "update.yml", "-R", TAP, check=False)
        say(
            f"done — https://github.com/{REPO}/releases/tag/v{version} "
            "(PyPI in a few minutes, Homebrew in ~10, the PPA within the hour)"
        )
        return 0
    except ReleaseError as exc:
        print(f"release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
