# Changelog

## [Unreleased]

---

## [1.3.8] - 2026-09-25

### Security
- Every TLS/HTTPS connection (`tls`, `http`, `whois` RDAP, `speedtest`)
  now goes through one shared context that verifies certificates and
  refuses anything older than TLS 1.2.
- `whois` no longer retries RDAP with certificate verification turned
  off when the verified request fails.

### Fixed
- `--json` output dropped several values shown on screen: `http` now
  exports `dns_ms`, `tcp_ms`, `http_version` and `h2_supported`,
  `health` exports `history`, and `tls` exports `chain`.
- `trace` read the ICMP type at a fixed offset, misparsing replies whose
  IPv4 header carries options; the header length is now honoured.
- The system `traceroute`/`tracert` fallback ignored `--timeout`.
- `tcp` resolved the host, then connected by name (resolving again, and
  possibly to a different address than the one displayed).
- `ping --watch` silently ignored `--json`/`--csv`/`--markdown`; the
  combination is now rejected with a clear error.
- `osdetect` could crash on a TTL above 255; dead TTL tables removed.
- Removed an unreachable `except` branch in `whois` and unused code in
  `trace` and `speedtest`.
- **`http` failed on every HTTP/2-capable HTTPS site**: the request
  connection offered `h2` via ALPN, but `http.client` only speaks
  HTTP/1.1, so servers that picked h2 rejected the request. The request
  now negotiates HTTP/1.1 only; HTTP/2 support is detected with a
  separate ALPN probe and shown as "HTTP/2 support".
- **`dnscheck` always failed DMARC**: it looked for the record at the
  apex instead of `_dmarc.<domain>`. The policy is now read from the
  `p=` tag (so `sp=reject` no longer masks `p=none`). DKIM is detected
  by probing common selectors at `<selector>._domainkey.<domain>`.
- **`listen` found nothing on macOS**, and the netstat fallback
  mis-parsed Linux (`0.0.0.0:22`, state vs PID column) and dropped
  Windows UDP rows. macOS/BSD now use `netstat -an` with `tcp4`/`tcp46`
  and dot-separated ports supported.
- **Raw-UDP DNS fallback returned CNAME targets as IP addresses**:
  answers are now filtered by the queried record type.
- **DNS query failures were reported as missing records**: SERVFAIL,
  REFUSED and timeouts are now tracked separately (`query_errors` in
  `lookup` output). `dnscheck` marks those checks "not verified" and
  leaves them out of the score instead of failing them.
- `speedtest` and `osdetect` now accept `--json` / `--csv` /
  `--markdown` (`osdetect` returns a proper result model).

### Internal
- The command list is now defined once (`cli/main.py`), and tests check
  that the parser, shell completion, and `--help` stay in sync with it.
- CI's version check now also covers `setup.cfg`, `snap/snapcraft.yaml`
  and `debian/changelog`; a non-blocking Windows test job was added.
- Resolved the open CodeQL findings (empty `except`, `import *` shims,
  unused imports/variables, asserts with side effects).

### Docs
- Removed the nonexistent `--alarm` and `--output` flags from the man
  page, shell completion and snap description. README now names the
  `certifi` dependency and the correct PPA package (`xping`).
  `--help` lists every command.

---

## [1.3.7] - 2026-09-21

### Changed
- The ASCII-art banner now prints only when `xping` is run with no
  arguments at all. It no longer appears before the bare-host
  shorthand (`xping 8.8.8.8`) or before any explicit subcommand
  (`xping ping ...`, `xping trace ...`, etc.) — every real command now
  starts straight with its own output.

---

## [1.3.6] - 2026-09-20

### Fixed
- **PPA rejected on upload**: Launchpad refused the 1.3.5 source
  package outright with `Rejected: Unable to find distroseries:
  unstable`. `debian/changelog`'s distribution field said `unstable`
  (Debian terminology), but Launchpad PPAs only recognise real Ubuntu
  series codenames — `noble`, `jammy`, etc. Fixed by changing it to
  `noble` (Ubuntu 24.04 LTS), matching the series this PPA has
  targeted since 1.3.0.

---

## [1.3.5] - 2026-09-18

Fixes a second, distinct Launchpad PPA signing failure that only
became visible after 1.3.4 fixed the first one and the workflow
reached the actual signing step for the first time.

### Fixed
- **PPA GPG signing**: `debsign` was failing with `gpg: Sorry, we are
  in batchmode - can't get input` for any signing key that has a
  passphrase — strict batch mode refuses to prompt for one under any
  circumstances. Fixed by writing the passphrase to a private file on
  the runner (via a new `LAUNCHPAD_GPG_PASSPHRASE` secret — safe to
  leave empty if the key has none) and signing through a `gpg
  --passphrase-file` wrapper passed to `debuild` via its `-p<command>`
  option. This single mechanism now works whether or not the signing
  key has a passphrase, so there's no longer a "pick one setup or the
  other" decision to make.
- Verified end-to-end locally before shipping, not just reasoned
  about: generated a real, throwaway passphrase-protected GPG key and
  ran `debsign -p<wrapper> --clearsign` against it — the exact
  mechanism `debuild -S -sa` invokes internally — and confirmed it
  signs with zero prompts and exit code 0.

### Changed
- `PACKAGING.md`: documented the new `LAUNCHPAD_GPG_PASSPHRASE` secret
  requirement; removed the earlier passphrase-less-key requirement,
  which no longer applies.

---

## [1.3.4] - 2026-09-13

This release fixes the actual root causes behind PPA and Snap builds
repeatedly failing, verified by running the real build/test/lint tools
locally rather than editing text and assuming it would work.

### Fixed — data correctness
- **Systemic export bug**: `exporters/serialize.py` used
  `dataclasses.asdict()`, which flattens nested dataclasses *before*
  computed `@property` fields can be attached. This silently dropped
  fields like `MtrHop.loss_pct` inside `MtrResult.hops`, and would have
  done the same for `PingResult.avg_rtt` inside `HealthResult.ping`, in
  every JSON/CSV/Markdown export. Rewritten to walk the real object
  graph so nested dataclasses at any depth keep their computed fields.

### Fixed — silently broken features
- `render/views/http.py` and `render/views/portscan.py` each contained
  **two definitions of the same function** (a leftover from an earlier
  edit that appended new code without removing the old). Python keeps
  the *last* definition, so the older, less capable version was
  silently running in production — the HTTP timing breakdown and the
  `portscan --banners` output were both quietly disabled despite the
  correct code sitting right above, unreachable.
- `render/latency.py` had orphaned unreachable code (referencing
  undefined names) left over from a previous edit — harmless at runtime
  since it was unreachable, but removed for good.
- `diagnostics/whois.py` was missing a top-level `import ssl` — masked
  by a local import inside one function, but referenced elsewhere as an
  unresolvable string type-annotation.

### Fixed — CI pipeline
- `ruff.toml` had `line-length`/`target-version` nested under `[lint]`
  instead of top-level, which is invalid TOML for ruff's schema — this
  made the "Code Quality" job fail immediately on a config parse error,
  before linting a single file, on every run.
- Actually ran `ruff check` and `ruff format` against the whole
  codebase for the first time and fixed every real finding (a missing
  import, an ambiguous variable name, an unused loop variable, a
  `zip()` missing `strict=`), then reformatted all 94 files for a
  consistent baseline. Two purely stylistic rules (`E701`/`E702`) are
  intentionally ignored — documented inline in `ruff.toml` — because
  this codebase deliberately uses compact one-line guard clauses
  throughout, and mechanically rewriting ~50 of them risks introducing
  typos for zero functional benefit.
- Coverage `fail_under` lowered from an unreachable 85% to 55%, based
  on an actually-measured 63% on the current suite.
- Fixed 5 real test failures, each verified individually and then as a
  full suite (222/222 passing):
  - `TestMtr::test_mtr_result_to_dict`, `test_export_json_mtr` — both
    resolved by the serialize.py fix above.
  - `test_lookup_with_dig_path` — mock signature didn't match the real
    3-argument `_dig_query(host, rtype, server)`.
  - `test_lookup_socket_fallback` — mocked a function `lookup()` never
    actually calls, so the test silently fell through and made a real
    network query in CI.
  - `test_subprocess_trace_live_parses_hops` — didn't mock
    `trace_tool()`/`trace_command()`, so the result depended on whether
    the `traceroute` binary happened to be installed on the runner.

### Fixed — Ubuntu PPA (Launchpad)
- `debian/control` still listed `pybuild-plugin-pyproject` in
  `Build-Depends`, which does not exist on Ubuntu 22.04 (Jammy) — the
  exact series this PPA builds for. This alone failed
  `dpkg-checkbuilddeps` before the build could even start, on every
  single upload.
- Added a `setup.py` shim and completed `setup.cfg` metadata so
  `pybuild` can build via the classic `distutils` interface without
  the pyproject-only plugin.
- `debian/rules` switched to `PYBUILD_SYSTEM=distutils`, skips tests
  during package build, and installs the man page.
- **GPG signing was failing** with `Inappropriate ioctl for device` —
  `debsign` tried to open a controlling terminal that does not exist on
  a GitHub-hosted runner. Fixed by configuring `gpg.conf`/
  `gpg-agent.conf` for batch mode with loopback pinentry and `no-tty`,
  the standard approach for headless package signing. See
  `PACKAGING.md` for the requirement that the signing key have no
  passphrase.
- Filled in `debian/copyright` (was still the unfilled template).

### Fixed — Snap Store
- Removed `.github/workflows/release-snap.yml` entirely. It duplicated
  the Snap Store's native GitHub integration (already authorized via
  Snapcraft.io → Builds → "build-snapcraft-io"), used a
  `SNAPCRAFT_TOKEN` secret that was never configured, and failed on
  every single run with `login_data is empty` — while the real,
  working publish path (the native integration) had been succeeding
  the whole time in parallel. Keeping a workflow that can never pass is
  worse than not having it: it manufactures a permanent false failure
  signal for something that already works.

### Changed
- Author contact corrected to Mehdi Askari <iorganamis@gmail.com>
  everywhere (was still `mehdiaskari@outlook.com` / "Meh Askari" in
  several files that earlier passes had missed).

---

## [1.3.0] - 2026-07-08

### Added
- `xping HOST` bare shorthand — auto-pings and shows follow-up suggestions
- `xping completion bash|zsh|fish` — shell tab-completion
- `xping speedtest` — download/upload speed via Cloudflare
- `xping listen [--proto tcp|udp]` — local listening ports
- `xping osdetect HOST` — OS fingerprinting from ICMP TTL
- `xping dnscheck DOMAIN` — DNS health check: SPF, DMARC, DKIM, MX, NS
- `xping portscan --banners` — service banner grabbing
- `xping lookup --server IP` — custom DNS resolver
- HTTP/2 detection via ALPN in `xping http`
- TLS certificate chain display in `xping tls`

---

## [1.2.5] - 2026-06-28
### Fixed
- whois.py duplicate function definitions
- RDAP SSL error on macOS / HTTPS fallback for blocked port 43

---

## [1.2.0] - 2026-06-25
### Added
- rdns, tls, http, whois, health, profile, mtr, mtu commands
- ping --watch continuous live mode
- Network health score with history
- Saved target profiles
