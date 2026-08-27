# Changelog

## [1.3.1] - 2026-07-12

### Changed
- Author email updated to iorganamis@gmail.com across all files
- Author name corrected to Mehdi Askari in all metadata, packaging, and documentation

### Fixed
- Man page date and author info corrected
- snap/snapcraft.yaml version and description updated
- debian/changelog version entry updated

---

## [1.3.0] - 2026-07-08

### Added
- `xping HOST` bare shorthand — auto-pings and shows follow-up suggestions
- `xping completion bash|zsh|fish` — shell tab-completion script generator
- `xping speedtest` — download/upload speed via Cloudflare (no iperf3)
- `xping listen [--proto tcp|udp]` — local listening ports with process names and PIDs
- `xping osdetect HOST` — OS fingerprinting from ICMP TTL
- `xping dnscheck DOMAIN` — DNS health check: SPF, DMARC, DKIM, MX, NS redundancy
- `xping portscan --banners` — service banner grabbing from open ports
- `xping lookup --server IP` — custom DNS resolver like `dig @8.8.8.8`
- HTTP/2 detection via ALPN in `xping http`
- Full timing breakdown in `xping http`: DNS · TCP connect · TTFB · total
- TLS certificate chain display in `xping tls`
- GitHub Actions: ci.yml, release-pypi.yml, release-launchpad.yml, release-snap.yml, codeql.yml
- CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, RELEASE.md, PACKAGING.md
- docs/publishing-guide.md — full publishing guide for PyPI, PPA, and Snap
- snap/snapcraft.yaml — Snap Store packaging
- .github/ISSUE_TEMPLATE/ — bug report and feature request templates
- .github/PULL_REQUEST_TEMPLATE.md

### Fixed
- KeyboardInterrupt during ping no longer shows a Python traceback — prints partial summary instead

---

## [1.2.5] - 2026-06-28

### Fixed
- `whois.py` had duplicate function definitions causing old code to run — completely rewritten
- RDAP query on macOS SSL error — now tries certifi then `_create_unverified_context`
- RDAP error message for `.ir` TLD showed wrong URL (verisign) — now TLD-aware
- `.ir` removed from `_RDAP_KNOWN` (nic.ir does not support RDAP)
- Retry logic added: port 43 tries 2× with 3s timeout, RDAP tries 3×
- `xping all` banner printed twice — extra `print(banner())` removed from `cmd_all`

### Added
- `tests/test_new_features.py` — 844-line comprehensive test suite for v1.2.0 features

---

## [1.2.0] - 2026-06-25

### Added
- `xping rdns IP` — reverse DNS with stdlib fallback to direct UDP query
- `xping tls HOST` — TLS/SSL certificate inspector with lifetime progress bar
- `xping http URL` — HTTP diagnostics with redirect chain, TTFB, headers
- `xping whois DOMAIN` — WHOIS port 43 with RDAP HTTPS fallback
- `xping health HOST` — network health score 0-100 with history trend sparkline
- `xping mtr HOST` — combined live traceroute + per-hop ping
- `xping mtu HOST` — path MTU discovery via binary search
- `xping ping HOST --watch` — continuous live ping with sparkline and min/avg/max
- `xping profile` subcommands — saved target presets in `~/.xping/profiles.json`
- `render.progress.clear_lines(n)` — ANSI cursor-up helper for live redraws
- All new commands support `--json`, `--csv`, `--markdown`, `--output`

---

## [1.1.0] - 2026-06-20

### Added
- Layered package layout: `cli/`, `diagnostics/`, `models/`, `exporters/`, `render/`
- `xping all` bundle: lookup, ping, trace, TCP 443/80
- `--json`, `--csv`, `--markdown` export flags on all commands
