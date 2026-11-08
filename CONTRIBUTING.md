# Contributing to xping

## Development Setup

```bash
git clone https://github.com/mehaskari/xping.git
cd xping
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Start with [ARCHITECTURE.md](ARCHITECTURE.md): how a command runs, the
long-running modes (watch, alerts, monitor) and what every module does.

## Workflow

`main` is protected: changes land through pull requests, and a PR can
only merge once the required checks pass. They are the tests on Linux
and macOS for Python 3.10–3.14 and on Windows (3.12), lint, type check,
version consistency, the build, the Debian package (lintian and
autopkgtest), the Fedora package (rpmlint and install) and CodeQL.

1. Branch from `main` (`fix/…`, `feat/…`, `docs/…`); one change per pull
   request.
2. Commit with a message that says what changed and why.
3. Push and open a PR using the template.
4. Before merging, wait until **every** check has finished green, not
   only the required ones, and look at the CodeQL alerts of the PR
   (`gh api 'repos/mehaskari/xping/code-scanning/alerts?ref=refs/pull/N/merge&state=open'`):
   fix every alert that is new compared with `main`, notes included,
   since a `note` does not fail the check. Then merge.
5. A macOS job that GitHub cancels before it ran a step (no runner was
   free) is not a failure: run it again.

## Documentation is part of the change

A pull request that changes behaviour updates its documentation in the
same pull request. Which file covers what:

| Change | Update |
|--------|--------|
| A command or option (new, changed, removed) | `docs/guide.md` (its section and option table; a test checks every long option), `man/xping.1`, `README.md` (usage and features), `docs/changelog.md` |
| Anything users notice | `docs/changelog.md` under `## [Unreleased]` |
| A new module, or a module's job changes | `ARCHITECTURE.md` (a test checks that every module is in its map) |
| Files written, ports opened, hosts contacted | the "Files & privacy" tables in `README.md` and `docs/guide.md` §7, `SECURITY.md`, `man/xping.1` FILES |
| How to develop, test or merge | `CONTRIBUTING.md` |
| Packaging or release workflows | `PACKAGING.md`, `RELEASE.md` |
| Supported versions (after a minor release) | `SECURITY.md` |
| The landing page's starting points | `docs/index.md` |

Docs that describe the code are wrong as soon as the code moves on; when
you notice one, fix it in the pull request you are working on.

## Before every commit

Run these locally — they are exactly what CI runs, so if they pass here
they pass there:

```bash
pytest --cov=xping --cov-report=term-missing
ruff check xping/ --config ruff.toml
ruff format --check xping/ --line-length 100
mypy                       # settings in pyproject.toml [tool.mypy]
```

- **Coverage** must stay at or above the `fail_under` value in
  `pyproject.toml`. It is a ratchet: raise it when coverage grows, never
  lower it.
- **Types:** every module is type-checked, with no exceptions; new code
  must pass mypy too. Please don't add `[[tool.mypy.overrides]]` with
  `ignore_errors`.

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
Releases are one command, `python3 scripts/release.py X.Y.Z`; see
[RELEASE.md](RELEASE.md).

## Screenshots

The README's screenshots (`docs/assets/*.svg`) are real xping runs drawn
by `scripts/screenshot.py`, which runs a command in a pseudo-terminal and
writes what is left on screen as an SVG:

```bash
python3 scripts/screenshot.py docs/assets/tls.svg -- tls github.com
```

To refresh all of them from a clean network, run the **Screenshots**
workflow and commit the files it produces:

```bash
gh workflow run screenshots.yml
gh run download --name screenshots --dir docs/assets
```

The repository's social preview (the image shown when a link to it is
shared) is `docs/assets/social-preview.png`, rendered from
`scripts/social-preview.html` with headless Chrome (the command is at the
top of that file) and uploaded under Settings → Social preview.

## A lesson this project learned the hard way

Several recurring bugs in this codebase (a systemic export bug, two
files with silently duplicated functions, an orphaned code block, a
malformed lint config) all had the same root cause: changes were
edited in as text without ever actually running the test suite or
linter against the result. **Never claim a fix works without running
it.** `pytest` and `ruff check` take a few seconds; guessing costs
hours down the line.

## Writing tests

- **No network and no real waiting.** Pass diagnostics a fake clock, a
  fake `sleep` and a fake runner (see `Clock` in `tests/test_monitor.py`)
  and mock sockets and subprocesses. A test that needs a server binds
  127.0.0.1 on a free port and stops it in `finally`.
- **No proxy.** Open local URLs with
  `urllib.request.build_opener(urllib.request.ProxyHandler({}))`: Debian
  package builds set a dead `http_proxy`.
- **Windows runs the suite too.** Skip what is POSIX-only (file modes,
  signals) with `pytest.mark.skipif(sys.platform == "win32", …)` rather
  than letting it fail.
- **Test the behaviour, not the implementation:** what the user sees,
  what is exported, which exit code, which alert. A bug fix starts with a
  test that fails without it.

## Code Style

```bash
ruff check xping/ --config ruff.toml --fix
ruff format xping/ --line-length 100
```

Two rules are intentionally ignored (see `ruff.toml` for why):
`E701`/`E702` — this codebase deliberately uses compact one-line guard
clauses (`except ValueError: pass`) throughout.

No new external dependencies without discussion — xping is stdlib +
`certifi` only. Compare with how the surrounding code does it, and match
its naming, comments and idiom.

## Adding a New Command

1. `xping/models/NAME.py` — dataclass + `to_dict()`
2. `xping/models/__init__.py` — import + `__all__`
3. `xping/exporters/serialize.py` — add a `_COMPUTED` entry if the model
   has computed (`@property`) fields that should appear in exports
4. `xping/exporters/tables.py` — rows for `--csv` / `--markdown` if the
   result has natural rows (otherwise it exports `field,value` pairs)
5. `xping/diagnostics/NAME.py` — diagnostic function taking `quiet=`
   (and `family=` if it resolves hosts — use `diagnostics/resolve.py`)
6. `xping/render/views/NAME.py` — `print_result()`; import it where it is
   used (`from xping.render.views import NAME as NAME_view`)
7. `xping/verdict.py` — when does the result count as a failure
   (exit code 1)? Add thresholds here if the command gets any.
8. `xping/cli/commands.py` — `cmd_NAME()` handler that **returns** the
   result. It is found by its name: there is no dispatch table to edit
   (a test checks that every subcommand has a handler).
9. `xping/cli/parser.py` — subcommand + flags; add it to the `--help`
   epilog (a test checks this)
10. Only if its results should be kept over time: one entry in
    `TARGETS` in `xping/diagnostics/history.py` (how to name the target).
    That alone gives the command `--save` and makes `xping history` and
    `xping report` accept it.
11. `man/xping.1` — COMMANDS entry, OPTIONS section and an example; if
    the command writes a file, opens a port or contacts a third party,
    the tables in "Documentation is part of the change" above
12. `README.md` — usage section; `docs/changelog.md` — entry
13. `docs/guide.md` — a `#### \`xping NAME\`` section with every option
    (it is also the documentation site: preview with
    `pip install -r docs/requirements.txt && mkdocs serve`; the site is
    built with `--strict`, so broken links or section anchors fail CI)
    (a test checks that each command and long option is documented)
14. Write real tests, mock all network calls, and **run them**.

Shell completion needs no changes: `xping/cli/completion.py` reads
commands, options, choices and help text from the parser. If a new
positional argument should complete to hosts, files or profiles, map its
`dest` in `_POSITIONAL_KINDS` there.

## Tests that need real shells

`tests/test_completion.py` drives real `bash` and `zsh` (via `zpty`) to
check what Tab actually offers. They skip automatically when the shell
is not installed (and on Windows). macOS CI runners have both.
