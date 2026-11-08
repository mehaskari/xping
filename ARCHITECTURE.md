# xping architecture

How the code is laid out and how a command runs, for anyone changing it.
User-facing behaviour is in [docs/guide.md](docs/guide.md); how to work on
the project (setup, checks, pull requests) is in
[CONTRIBUTING.md](CONTRIBUTING.md).

This file is kept in step with the code: `tests/test_docs.py` fails when a
module is missing from the [module map](#module-map), so a new module comes
with a line here in the same pull request.

## Principles

- **Standard library only.** The one dependency is `certifi` (CA
  certificates for systems without a usable store). HTTP servers, TOML,
  ICMP, DNS parsing and the terminal UI are all stdlib. A new dependency
  needs a discussion first.
- **One result object per command.** A diagnostic returns a dataclass from
  `xping/models/`. Everything else (the terminal view, JSON / CSV /
  Markdown, the exit code, history, `diff`, alerts) is derived from that
  object, never from what was printed.
- **No root, no shell.** ICMP uses unprivileged sockets where the OS allows
  them; external tools run from argument lists, never through a shell.
- **Remote text is untrusted.** Anything that came from the network is
  stripped of escape sequences before it is printed and HTML-escaped
  before it goes into a page.
- **Testable without the network.** Diagnostics take their I/O (clock,
  sleep, runner, sockets) as parameters or behind small functions that
  tests replace.

## How a command runs

```
xping tls example.com --min-days 30 --json
  │
  ├─ cli/main.py        deprecated.rewrite() → build_parser() → config.apply()
  │                     (~/.xping/config.toml becomes parser defaults)
  ├─ cli/commands.py    cmd_tls(args): calls the diagnostic, then
  │                     emit_export() when --json / --csv / --markdown
  ├─ diagnostics/tls.py tls(host, …, quiet=…) → TlsResult   (models/tls.py)
  │                     prints through render/views/tls.py unless quiet
  ├─ cli/export.py      exporters/serialize.py → json / csv / markdown
  ├─ verdict.py         evaluate(result, args) → failures → exit code 0 / 1
  └─ cli/main.py        --save: diagnostics/history.record()
```

- **Dispatch has no table.** `cli/main.py` maps the subcommand `NAME` to
  `commands.cmd_NAME`; a test checks that every parser subcommand has one.
- **Exit codes:** 0 passed, 1 failed (unreachable, error, or a threshold
  such as `--max-loss`), 2 usage error (`UsageError` or argparse), 130
  Ctrl-C. `verdict.py` is the only place that decides pass or fail, and it
  reads thresholds by attribute name, so the same rules serve argparse
  namespaces and check-file entries.
- **Output modes:** with an export flag or `--quiet` the diagnostic gets
  `quiet=True` and prints nothing; the result is exported to stdout.
  Messages about deprecated options go to stderr so they never mix with
  exported data.
- **Errors:** an unexpected exception prints one line and exits 1;
  `XPING_DEBUG=1` shows the traceback.

## Long-running modes

### Watch (`--watch`, `--until-up`)

`diagnostics/watch.py` repeats one probe. Each run goes through a
`StateFilter` (`statefilter.py`): a target is DOWN only after `fail_after`
failures in a row and UP after `recover_after` passes, so alerts and the
state follow confirmed changes, while uptime counts every run.

### Alerts

`diagnostics/notify.py` holds one `Notifier` per target. It turns
confirmed changes into `down` / `up` events, plus `still_down` reminders
(`--remind`). Desktop notifications go through `osascript` /
`notify-send`; webhooks are posted on a background thread, so a slow
endpoint never delays a check. `_delivery()` picks the body from the URL:
Telegram and ntfy get their own shape, everything else the plain event.

### Monitor

`diagnostics/monitor.py` runs every check of a check file
(`diagnostics/check.py` loads and validates it) on its own schedule:

```
            ┌──────────────── main thread ────────────────┐
check file ─┤ _FileWatch → reload → _merge (keep numbers)  │
            │ due checks → run_entries() (thread pool)     │
            │ _Tracker.apply → MonitoredCheck.record       │──► live table / change lines
            │               → StateFilter → Notifier       │──► alerts
            │ every 60 s and at exit → monitor_state.save  │──► ~/.xping/monitor/
            └──────────────┬───────────────────────────────┘
                           │ lock
            ┌──────────────┴───────────────┐
            │ HTTP server thread(s)        │ /metrics      (exporters/prometheus.py)
            │ prometheus.MetricsServer     │ / , /status.json (exporters/status_page.py)
            └──────────────────────────────┘
```

- **One lock** guards a check's state. The main thread holds it while it
  applies a run or a reload; the HTTP threads hold it while they render.
  A page can never show a run half applied.
- **Bounded memory.** `MonitoredCheck` keeps running totals and only the
  latest `KEEP_SAMPLES` runs, so a monitor can run for months.
- **Identity.** A check is the same check while its name, type and target
  stay. That key decides what a reload keeps and what `--resume` restores.
- **Servers.** `--metrics` and `--status-page` each name an address; equal
  addresses share one server. They listen on 127.0.0.1 unless a host is
  given. The handler answers GET and HEAD and sends `nosniff` and a strict
  Content-Security-Policy.
- **Background service.** `diagnostics/service.py` writes a launchd agent
  or a systemd user unit (mode 600) that runs the same monitor command,
  always with `--resume`.

## Storage

Everything lives under `~/.xping/`; nothing is written without a command
that asks for it.

| Path | Written by | Module |
|------|------------|--------|
| `config.toml` | you (xping only reads it) | `cli/config.py` |
| `checks.toml` | `xping check --init` | `diagnostics/check.py` |
| `history/<command>/<target>.jsonl` | `--save` | `diagnostics/history.py` |
| `health_history.json` | `xping health` | `diagnostics/health.py` |
| `profiles.json` | `xping profile` | `diagnostics/profile.py` |
| `monitor/<hash>.json` | `xping monitor --resume` | `diagnostics/monitor_state.py` |
| `monitor.log` | the background monitor | `diagnostics/service.py` |
| `completions/` | `xping completion --install` | `cli/completion.py` |

Files are written in one step (a temporary file, then `os.replace`) where
a half-written file would hurt. Files that can hold a secret (a webhook
URL in the service file) or that describe your checks (`monitor/`) are
mode 600.

## Module map

Per-command modules follow one pattern and are not listed one by one:
`diagnostics/NAME.py` does the work, `models/NAME.py` holds the result,
`render/views/NAME.py` draws it. The steps for a new command are in
[CONTRIBUTING.md](CONTRIBUTING.md#adding-a-new-command).

### Command line: `xping/cli/`

| Module | Role |
|--------|------|
| `cli/main.py` | Entry point: config, bare-host shortcut, dispatch, exit code, `--save` |
| `cli/parser.py` | Every subcommand and option, and the argument types that validate them |
| `cli/commands.py` | `cmd_NAME` handlers: call the diagnostic, wire watch mode and alerts, return the result |
| `cli/export.py` | `--json` / `--csv` / `--markdown` / `--quiet` handling |
| `cli/config.py` | `~/.xping/config.toml` as parser defaults |
| `cli/completion.py` | bash / zsh / fish completion generated from the parser |
| `cli/deprecated.py` | Old option spellings rewritten (with a warning) until 2.0 |
| `cli/errors.py` | `UsageError` (exit 2) |
| `__main__.py` | `python -m xping` |

### Shared logic

| Module | Role |
|--------|------|
| `verdict.py` | Pass / fail of every result type, thresholds, exit code 1 |
| `statefilter.py` | Debounced up / down state, and outages in a series of runs |
| `diagnostics/resolve.py` | Host resolution with `-4` / `-6` |
| `diagnostics/sslctx.py` | The one TLS client context (system store + certifi, TLS 1.2+) |
| `diagnostics/icmp.py` | ICMP / ICMPv6 echo without root |
| `diagnostics/platform_cmds.py` | `ping` / `traceroute` command lines per OS (the fallback) |
| `diagnostics/deps.py` | Which system tools are installed (`xping deps`) |
| `diagnostics/profile.py` | Saved targets, resolved in every host argument |
| `diagnostics/history.py` | `--save` storage; which metric each command follows over time |
| `diagnostics/check.py` | Check files: load, validate, run many checks in parallel |
| `diagnostics/watch.py` | `--watch` / `--until-up` loop |
| `diagnostics/notify.py` | Desktop and webhook alerts, reminders |
| `diagnostics/monitor.py` | `xping monitor`: schedule, reload, servers, alerts |
| `diagnostics/monitor_state.py` | `--resume` state files |
| `diagnostics/service.py` | `--install-service`: launchd / systemd |
| `diagnostics/report.py` | History to the data of `xping report` |
| `diagnostics/diff.py` | Compare two exported results |
| `diagnostics/bundle.py` | `xping all`: lookup, ping, trace and TCP in one run |
| `diagnostics/asn.py` | IP to network operator (Team Cymru DNS), for `--asn` |
| `diagnostics/dnssec.py` | DNSSEC validation, used by `dnscheck` |
| `diagnostics/tcptrace.py` | TCP SYN traceroute without root (`trace --tcp`) |
| `diagnostics/osdetect.py` | `xping osdetect`: OS guess from TTL and TCP window |

The remaining `diagnostics/*.py` are the per-command modules: `blocklist`,
`dnscheck`, `doctor`, `health`, `http`, `ipscan`, `listen`, `lookup`,
`mtr`, `mtu`, `net`, `ntp`, `ping`, `portscan`, `propagation`, `rdns`,
`smtp`, `speedtest`, `sweep`, `tcp`, `tls`, `trace`, `udp`, `whois`,
`wifi`. They are listed here so the map stays complete:
`diagnostics/blocklist.py`, `diagnostics/dnscheck.py`,
`diagnostics/doctor.py`, `diagnostics/health.py`, `diagnostics/http.py`,
`diagnostics/ipscan.py`, `diagnostics/listen.py`, `diagnostics/lookup.py`,
`diagnostics/mtr.py`, `diagnostics/mtu.py`, `diagnostics/net.py`,
`diagnostics/ntp.py`, `diagnostics/ping.py`, `diagnostics/portscan.py`,
`diagnostics/propagation.py`, `diagnostics/rdns.py`, `diagnostics/smtp.py`,
`diagnostics/speedtest.py`, `diagnostics/sweep.py`, `diagnostics/tcp.py`,
`diagnostics/tls.py`, `diagnostics/trace.py`, `diagnostics/udp.py`,
`diagnostics/whois.py`, `diagnostics/wifi.py`.

### Output: `xping/exporters/` and `xping/render/`

| Module | Role |
|--------|------|
| `exporters/serialize.py` | Dataclass to dict, including the computed properties listed in `_COMPUTED` |
| `exporters/json.py`, `exporters/csv.py`, `exporters/markdown.py` | The export formats |
| `exporters/tables.py` | Rows of a result for CSV and Markdown |
| `exporters/html_report.py` | `xping report`: one self-contained HTML page |
| `exporters/prometheus.py` | `--metrics` text format, the listen address parser and the HTTP server |
| `exporters/status_page.py` | `--status-page` HTML and `/status.json` |
| `models/_export.py` | `to_dict()` shared by every model |
| `render/ansi.py` | Colours, `NO_COLOR`, visible width, stripping escapes |
| `render/layout.py` | Banner, section headers, key-value rows, terminal width |
| `render/tables.py` | Terminal tables |
| `render/latency.py` | Latency colours, sparklines, RTT bars |
| `render/animations.py` | Spinners and other live widgets |
| `render/progress.py` | Progress lines, in-place redraw |
| `render/errors.py` | `error()` and `warn()` |
| `render/views/_asn.py`, `render/views/_cert.py` | Helpers shared by several views |

### Compatibility shims

`ping.py`, `trace.py`, `tcp.py`, `lookup.py`, `ipscan.py`, `portscan.py`,
`sweep.py`, `platform_cmds.py`, `deps.py` and `serialize.py` at the top of
the package re-export the modules that moved under `diagnostics/` and
`exporters/`, so old imports keep working. New code imports the real
modules.

## Tests

`tests/` mirrors the features (`test_monitor.py`, `test_status_page.py`,
…). Conventions:

- **No network, no sleeping.** Diagnostics are given a fake clock, a fake
  `sleep` and a fake runner; servers bind 127.0.0.1 on a free port.
- **No proxy.** Tests that talk to a local server open URLs with
  `ProxyHandler({})`: Debian builds set a dead `http_proxy`.
- **Real shells where it matters.** Completion tests drive real bash and
  zsh and skip when they are missing.
- **Docs are tested.** `tests/test_docs.py` checks that every command and
  long option is in the guide and every module is in this file.

## Packaging and releases

The version lives in seven files, bumped together by
`scripts/release.py`, which also opens the release pull request, waits
for CI and CodeQL, tags, and starts the tap update. A tag publishes to
PyPI, GitHub Releases, the Launchpad PPA, COPR, Homebrew and the Snap
Store; see [RELEASE.md](RELEASE.md) and [PACKAGING.md](PACKAGING.md).
