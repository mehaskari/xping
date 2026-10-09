"""scripts/release.py: the text changes it makes, checked on the real files
(git, gh and the network are not touched)."""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "scripts" / "release.py").exists():  # not shipped in the PyPI sdist
    pytest.skip("scripts/release.py is not in this source tree", allow_module_level=True)
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_bumps_every_versioned_file_consistently():
    old = release.current_version((ROOT / "pyproject.toml").read_text())
    for name in release.VERSIONED:
        new = release.bump_text(name, (ROOT / name).read_text(), "9.8.7")
        assert "9.8.7" in new and new.count("9.8.7") == 1, name
    man = release.bump_man((ROOT / "man/xping.1").read_text(), "9.8.7", "2030-01-02")
    assert '.TH XPING 1 "2030-01-02" "xping 9.8.7"' in man
    assert old != "9.8.7"


def test_changelog_notes_dating_and_debian_entry():
    changelog = (
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- **`xping thing`: does it.** More\n"
        "  text.\n\n### Fixed\n- a `bug`\n\n## [1.0.0] - 2026-01-01\n- old\n"
    )
    notes = release.unreleased_notes(changelog)
    assert notes == ["xping thing: does it. More text.", "a bug"]
    assert "## [1.1.0] - 2030-01-02" in release.date_changelog(changelog, "1.1.0", "2030-01-02")
    entry = release.debian_entry("1.1.0", ["word " * 30], "Tue, 01 Jan 2030 00:00:00 +0000")
    lines = entry.splitlines()
    assert lines[0] == "xping (1.1.0-1) noble; urgency=medium"
    assert all(len(ln) <= 72 for ln in lines)
    assert lines[2].startswith("  * word") and lines[3].startswith("    word")
    assert re.search(r"^ -- .+  Tue, 01 Jan 2030", entry, re.M)


def test_errors():
    with pytest.raises(release.ReleaseError, match="Unreleased"):
        release.unreleased_notes("# Changelog\n\n## [1.0.0] - x\n")
    with pytest.raises(release.ReleaseError, match="empty"):
        release.unreleased_notes("## [Unreleased]\n\n### Added\n\n## [1.0.0]\n")
    with pytest.raises(release.ReleaseError, match="setup.cfg"):
        release.bump_text("setup.cfg", "[metadata]\nname = xping\n", "1.0.0")


def test_versions_compare_numerically():
    assert release._key("1.10.0") > release._key("1.9.9")
