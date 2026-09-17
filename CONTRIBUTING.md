# Contributing to xping

## Development Setup

```bash
git clone https://github.com/mehdiaskari/xping.git
cd xping
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Before every commit

Run these locally — they are exactly what CI runs, so if they pass here
they pass there:

```bash
pytest --cov=xping --cov-report=term-missing
ruff check xping/ --config ruff.toml
ruff format --check xping/ --line-length 100
```

## Version Bump Protocol

**All four files must be updated together, every time:**

| File | Pattern |
|------|---------|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `xping/__init__.py` | `__version__ = "X.Y.Z"` |
| `man/xping.1` | `.TH XPING 1 "YYYY-MM-DD" "xping X.Y.Z"` |
| `docs/changelog.md` | `## [X.Y.Z] - YYYY-MM-DD` |

Verify:
```bash
python3 -c "
import re, sys
files = {
    'pyproject.toml':   (open('pyproject.toml').read(),   r'version = \"(.+?)\"'),
    'xping/__init__.py':(open('xping/__init__.py').read(),r'__version__\s*=\s*\"(.+?)\"'),
    'man/xping.1':      (open('man/xping.1').read(),      r'\"xping ([0-9]+\.[0-9]+\.[0-9]+)\"'),
}
v = {k: re.search(p,t).group(1) for k,(t,p) in files.items()}
assert len(set(v.values()))==1, f'MISMATCH: {v}'
print('OK', list(v.values())[0])
"
```
The CI `version-check` job runs this automatically on every push.

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
4. `xping/diagnostics/NAME.py` — diagnostic function
5. `xping/render/views/NAME.py` — `print_result()`
6. `xping/render/views/__init__.py` — import
7. `xping/cli/commands.py` — `cmd_NAME()` handler
8. `xping/cli/parser.py` — subcommand + flags
9. `xping/cli/main.py` — dispatch table entry
10. `xping/cli/completion.py` — `_COMMANDS` + `_FLAGS`
11. `man/xping.1` — `.TP` entry + example
12. `docs/changelog.md` — entry
13. Write real tests, mock all network calls, and **run them**.
