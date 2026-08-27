# Contributing to xping

## Setup

```bash
git clone https://github.com/mehdiaskari/xping.git
cd xping
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Version Bump Protocol

**All 4 files must be updated atomically:**

| File | Pattern |
|------|---------|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `xping/__init__.py` | `__version__ = "X.Y.Z"` |
| `man/xping.1` | `.TH XPING 1 "YYYY-MM-DD" "xping X.Y.Z"` |
| `docs/changelog.md` | `## [X.Y.Z] - YYYY-MM-DD` |

**Verify:**
```bash
python3 -c "
import re, sys
files = {
    'pyproject.toml':   (open('pyproject.toml').read(),   r'version = \"(.+?)\"'),
    'xping/__init__.py':(open('xping/__init__.py').read(),r'__version__\s+=\s+\"(.+?)\"'),
    'man/xping.1':      (open('man/xping.1').read(),      r'\"xping ([0-9]+\.[0-9]+\.[0-9]+)\"'),
}
v = {k: re.search(p,t).group(1) for k,(t,p) in files.items()}
assert len(set(v.values()))==1, f'MISMATCH: {v}'
print('✔', list(v.values())[0])
"
```

## Tests

```bash
pytest                                        # all
pytest --cov=xping --cov-report=term-missing  # with coverage
pytest -k "test_whois"                         # by name
```

Rules: no real network calls — use `unittest.mock.patch`.

## Code Style

```bash
ruff check xping/ && ruff format xping/
```

Line length: 100. No new external dependencies.

## Adding a New Command

1. `xping/models/NAME.py` — dataclass + `to_dict()`
2. `xping/models/__init__.py` — import + `__all__`
3. `xping/exporters/serialize.py` — `_COMPUTED` entry
4. `xping/diagnostics/NAME.py` — diagnostic function
5. `xping/render/views/NAME.py` — `print_result()`
6. `xping/render/views/__init__.py` — import
7. `xping/cli/commands.py` — `cmd_NAME()` handler
8. `xping/cli/parser.py` — subcommand + flags
9. `xping/cli/main.py` — dispatch table entry
10. `xping/cli/completion.py` — `_COMMANDS` + `_FLAGS`
11. `man/xping.1` — `.TP` entry + example in EXAMPLES
12. `docs/changelog.md` — entry

## Commit Messages

```
feat: add xping dnscheck command
fix: catch KeyboardInterrupt during ping
docs: update man page with --alarm flag
chore: bump version to 1.3.1
```
