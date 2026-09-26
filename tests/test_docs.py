"""The user guide must document every command and every long option."""

from pathlib import Path

from xping.cli.completion import model

GUIDE = (Path(__file__).resolve().parent.parent / "docs" / "guide.md").read_text(encoding="utf-8")
EXPORT_FLAGS = {"--json", "--csv", "--markdown", "--quiet"}  # documented once, in §3.3
FAMILY_FLAGS = {"--ipv4", "--ipv6"}  # documented once, in §3.2 (sections list -4 / -6)


def _section(name: str) -> str:
    """Text of the guide's '#### `xping NAME`' section."""
    heading = f"#### `xping {name}`"
    assert heading in GUIDE, f"docs/guide.md has no section {heading!r}"
    start = GUIDE.index(heading)
    end = GUIDE.find("\n#### ", start + len(heading))
    end = GUIDE.find("\n## ", start) if end == -1 else end
    return GUIDE[start:end]


def test_every_command_has_a_section():
    for name in model().subcommands:
        if name != "rm":  # alias of profile remove
            _section(name)


def test_every_long_option_is_documented_in_its_section():
    missing = []
    for name, cmd in model().subcommands.items():
        if name == "rm":
            continue
        text = _section(name)
        for command in [cmd, *cmd.subcommands.values()]:
            for flag in (f for option in command.options for f in option.flags):
                if flag in FAMILY_FLAGS:
                    if "`-4`, `-6`" not in text:
                        missing.append(f"{name}: -4 / -6")
                elif flag.startswith("--") and flag not in EXPORT_FLAGS and flag not in text:
                    missing.append(f"{name}: {flag}")
    assert not missing, "undocumented in docs/guide.md: " + ", ".join(sorted(set(missing)))


def test_shared_flags_documented_once():
    for flag in EXPORT_FLAGS | FAMILY_FLAGS:
        assert f"`{flag}`" in GUIDE or f"`-q`, `{flag}`" in GUIDE, flag


def test_table_of_contents_links_every_command():
    for name in model().subcommands:
        if name != "rm":
            assert f"(#xping-{name})" in GUIDE, f"contents has no link to xping {name}"
