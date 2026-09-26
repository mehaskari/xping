# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.4.x   | ✅ Active |
| < 1.4   | ❌ No longer supported |

## Reporting a Vulnerability

Do not open public GitHub Issues for security vulnerabilities.

- **Preferred**: GitHub → Security → Advisories → New draft security advisory
- **Email**: iorganamis@gmail.com — subject `[xping] Security: <description>`

Include: description, reproduction steps, potential impact.

## Response Timeline

| Stage | Timeframe |
|-------|-----------|
| Acknowledgement | 48 hours |
| Fix (critical) | 7 days |
| Fix (others) | 30 days |

## Security Design

xping is a **read-only diagnostic tool**: no daemon, no server, no
stored credentials, no `eval`/`exec`.

- **Privileges:** no root needed on macOS or Linux — ICMP uses
  unprivileged ping sockets where the OS allows them. Raw sockets are
  used only when xping already runs as root, and the system `ping` /
  `traceroute` are the fallback. xping never asks for elevation.
- **TLS:** every HTTPS/TLS connection (`tls`, `http`, `whois` RDAP,
  `speedtest`, `net`) verifies certificates against the system store
  plus `certifi` and refuses anything older than TLS 1.2. There is no
  option to disable verification.
- **Files written:** only under `~/.xping/` (profiles, health history,
  completion scripts). `xping completion --install` additionally adds a
  clearly marked block to the shell rc file, only when asked, and
  `--uninstall` removes exactly that block.
- **Network:** diagnostics contact the host you name. Features that
  contact third parties (`pool.ntp.org` for `ntp` unless you name a server,
  Cloudflare for `net`/`speedtest`/`doctor`, Apple's captive-portal
  check for `doctor`, Team Cymru
  DNS for `--asn`, public resolvers for `propagation`, WHOIS/RDAP
  registries for `whois`, spam blocklists for `blocklist`, 1.1.1.1/8.8.8.8 for the `dnscheck`
  DNSSEC check, the chosen provider for `lookup --doh`) are listed in the README under
  "Files & privacy"; `--asn` is opt-in and `net --no-public` keeps
  everything local.
- **Alerts:** `--webhook` sends the target name and check result only to
  the URL you pass. `--notify` hands the text to `osascript` /
  `notify-send` as arguments, never as script source or a shell line.
- **Subprocesses:** system tools (`ping`, `traceroute`, `dig`, `ss`,
  `netstat`, `ip`, `ifconfig`, `osascript`, `notify-send`, …) are run with argument lists, never
  through a shell.
