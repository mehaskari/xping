# Contributing to xping

## Development Setup

```bash
git clone https://github.com/mehaskari/xping.git
cd xping
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Workflow

`main` is protected: changes land through pull requests, and a PR can
only merge once the required CI checks pass (tests on Linux and macOS
for Python 3.10–3.12, lint, version consistency, build). Auto-merge is
enabled, so a PR merges by itself as soon as it is green.

1. Branch from `main` (`fix/…`, `feat/…`, `docs/…`).
2. Commit with a message that says what changed and why.
3. Push and open a PR using the template.
4. The Windows job is informational (not required); if it fails, its
   check-run annotations name the failing tests.

## Before every commit

Run these locally — they are exactly what CI runs, so if they pass here
they pass there:

```bash
pytest --cov=xping --cov-report=term-missing
ruff check xping/ --config ruff.toml
ruff format --check xping/ --line-length 100
```

## Version Bump Protocol

**All of these files must be updated together, every time:**

| File | Pattern |
|------|---------|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `xping/__init__.py` | `__version__ = "X.Y.Z"` |
| `man/xping.1` | `.TH XPING 1 "YYYY-MM-DD" "xping X.Y.Z"` |
| `setup.cfg` | `version = X.Y.Z` |
| `snap/snapcraft.yaml` | `version: 'X.Y.Z'` |
| `debian/changelog` | `xping (X.Y.Z-1) noble; …` (new top entry via `dch`) |
| `docs/changelog.md` | `## [X.Y.Z] - YYYY-MM-DD` |

Verify:
```bash
python3 -c "
import re, sys
files = {
    'pyproject.toml':   (open('pyproject.toml').read(),   r'version = \"(.+?)\"'),
    'xping/__init__.py':(open('xping/__init__.py').read(),r'__version__\s*=\s*\"(.+?)\"'),
    'man/xping.1':      (open('man/xping.1').read(),      r'\"xping ([0-9]+\.[0-9]+\.[0-9]+)\"'),
    'setup.cfg':        (open('setup.cfg').read(),        r'(?m)^version = (.+)$'),
    'snap/snapcraft.yaml': (open('snap/snapcraft.yaml').read(), r"(?m)^version: '(.+?)'"),
    'debian/changelog': (open('debian/changelog').read(), r'^xping \(([^)-]+)'),
}
v = {k: re.search(p,t).group(1) for k,(t,p) in files.items()}
assert len(set(v.values()))==1, f'MISMATCH: {v}'
print('OK', list(v.values())[0])
"
```
The CI `version-check` job runs this automatically on every push.
Releases themselves are described in [RELEASE.md](RELEASE.md).

## A lesson this project learned the hard way

Several recurring bugs in this codebase (a systemic export bug, two
files with silently duplicated functions, an orphaned code block, a
malformed lint config) all had the same root cause: changes were
edited in as text without ever actually running the test suite or
linter against the result. **Never claim a fix works without running
it.** `pytest` and `ruff check` take a few seconds; guessing costs
hours down the line.

## Code Style

```bash
ruff check xping/ --config ruff.toml --fix
ruff format xping/ --line-length 100
```

Two rules are intentionally ignored (see `ruff.toml` for why):
`E701`/`E702` — this codebase deliberately uses compact one-line guard
clauses (`except ValueError: pass`) throughout.

No new external dependencies without discussion — xping is stdlib +
`certifi` only.

## Adding a New Command

1. `xping/models/NAME.py` — dataclass + `to_dict()`
2. `xping/models/__init__.py` — import + `__all__`
3. `xping/exporters/serialize.py` — add a `_COMPUTED` entry if the model
   has computed (`@property`) fields that should appear in exports
4. `xping/exporters/tables.py` — rows for `--csv` / `--markdown` if the
   result has natural rows (otherwise it exports `field,value` pairs)
5. `xping/diagnostics/NAME.py` — diagnostic function taking `quiet=`
   (and `family=` if it resolves hosts — use `diagnostics/resolve.py`)
6. `xping/render/views/NAME.py` — `print_result()`
7. `xping/render/views/__init__.py` — import
8. `xping/cli/verdict.py` — when does the result count as a failure
   (exit code 1)? Add thresholds here if the command gets any.
9. `xping/cli/commands.py` — `cmd_NAME()` handler that **returns** the result
10. `xping/cli/parser.py` — subcommand + flags; add it to the `--help`
    epilog (a test checks this)
11. `xping/cli/main.py` — dispatch table entry
12. `man/xping.1` — COMMANDS entry, OPTIONS section and an example
13. `README.md` — usage section; `docs/changelog.md` — entry
14. Write real tests, mock all network calls, and **run them**.

Shell completion needs no changes: `xping/cli/completion.py` reads
commands, options, choices and help text from the parser. If a new
positional argument should complete to hosts, files or profiles, map its
`dest` in `_POSITIONAL_KINDS` there.

## Tests that need real shells

`tests/test_completion.py` drives real `bash` and `zsh` (via `zpty`) to
check what Tab actually offers. They skip automatically when the shell
is not installed (and on Windows). macOS CI runners have both.
