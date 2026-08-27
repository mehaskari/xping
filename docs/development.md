# Developer Guide

## Quick Start

```bash
git clone https://github.com/mehdiaskari/xping.git
cd xping
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
xping 8.8.8.8          # smoke test
pytest                  # run all tests
```

## Daily Workflow

```bash
pytest --tb=short -q                # tests
ruff check xping/ && ruff format xping/  # lint + format
xping ping 127.0.0.1 -c 2          # quick smoke test
```

## Environment Variables

| Variable | Effect |
|----------|--------|
| `XPING_DEBUG=1` | Print full tracebacks on errors |
| `NO_COLOR=1` | Disable all ANSI colour |

## Running Without Installing

```bash
python -m xping ping 8.8.8.8
python -m xping lookup github.com --full
```

## Man Page Preview

```bash
man ./man/xping.1
groff -man -Tascii man/xping.1 | less
```

## Debugging Raw Sockets

```bash
python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    print('raw sockets available')
    s.close()
except PermissionError:
    print('need root or cap_net_raw')
"

# Grant capability without sudo (Linux only)
sudo setcap cap_net_raw+ep $(which python3)
# Revoke
sudo setcap -r $(which python3)
```

## New Command Checklist

- [ ] `xping/models/NAME.py` — dataclass with `to_dict()`
- [ ] `xping/models/__init__.py` — import + `__all__`
- [ ] `xping/exporters/serialize.py` — `_COMPUTED` entry
- [ ] `xping/diagnostics/NAME.py` — diagnostic function
- [ ] `xping/render/views/NAME.py` — `print_result()`
- [ ] `xping/render/views/__init__.py` — import
- [ ] `xping/cli/commands.py` — `cmd_NAME()` handler
- [ ] `xping/cli/parser.py` — subcommand + flags
- [ ] `xping/cli/main.py` — dispatch table entry
- [ ] `xping/cli/completion.py` — `_COMMANDS` + `_FLAGS`
- [ ] `man/xping.1` — `.TP` entry + example
- [ ] `docs/changelog.md` — entry under upcoming version
- [ ] `tests/` — at least 3 tests

## Common Pitfalls

**`ModuleNotFoundError: No module named 'xping'`**
Run from parent directory or use `python -m xping`.

**`Version mismatch`**
One of the four version files wasn't updated. Run the version-check script.

**Tests fail with `socket.gaierror`**
A test makes a real network call. Wrap with `@patch('...socket.gethostbyname', return_value='1.2.3.4')`.
