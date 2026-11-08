# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.8.x   | ✅ Active |
| < 1.8   | ❌ No longer supported: please upgrade |

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

xping is a **read-only diagnostic tool**: no stored credentials, no
`eval`/`exec`, and nothing runs in the background or listens on the
network unless you ask for it.

- **Listening:** only `xping monitor --metrics` and `--status-page` open a
  port. They serve read-only pages (GET and HEAD), listen on 127.0.0.1
  unless you give a host, and have no authentication: on another address,
  everyone who can reach it sees each check's name, target and latest
  result. The status page has no scripts, loads nothing from the network,
  escapes every value from a check, and is sent with `nosniff` and a
  Content-Security-Policy that allows inline CSS only.
- **Background:** only `xping monitor --install-service` installs
  anything that keeps running (a launchd agent or a systemd user unit, as
  you, never as root); `--uninstall-service` removes it.

- **Privileges:** no root needed on macOS or Linux — ICMP uses
  unprivileged ping sockets where the OS allows them. Raw sockets are
  used only when xping already runs as root, and the system `ping` /
  `traceroute` are the fallback. xping never asks for elevation.
- **TLS:** every HTTPS/TLS connection (`tls`, `http`, `whois` RDAP,
  `speedtest`, `net`) verifies certificates against the system store
  plus `certifi` and refuses anything older than TLS 1.2. There is no
  option to disable verification.
- **Files written:** only under `~/.xping/` (profiles, health history,
  completion scripts, results saved with `--save` under
  `~/.xping/history/` — nothing is recorded without it — the monitor's
  `--resume` state under `~/.xping/monitor/` and the background monitor's
  log), plus the service file of `--install-service`. Files that can hold
  a secret (the service file, which contains any `--webhook` URL) or that
  describe your checks (`~/.xping/monitor/`) are readable only by you.
  `~/.xping/config.toml` is only ever read, and its
  values go through the same validation as command-line options. `xping completion --install` additionally adds a
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
  the URL you pass. A Telegram or ntfy URL is a secret (a bot token, a
  topic anyone can read); the guide says to treat it as a password. `--notify` hands the text to `osascript` /
  `notify-send` as arguments, never as script source or a shell line.
- **Subprocesses:** system tools (`ping`, `traceroute`, `dig`, `ss`,
  `netstat`, `ip`, `ifconfig`, `osascript`, `notify-send`, …) are run with argument lists, never
  through a shell.
- **Remote data:** text from servers (HTTP headers, SMTP banners, WHOIS,
  DNS records, Wi-Fi names) is stripped of terminal escape sequences and
  control characters before it is shown or exported. DNS responses are
  parsed with bounded pointer following, raw DNS queries use random IDs on
  connected sockets, and response sizes are capped (HTTP body, WHOIS).
- **Names as arguments:** names passed to `dig` use `-q`/`-t`, so a value
  starting with `-` can never become an option.
