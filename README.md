# xping

**Beautiful CLI network diagnostics — ping, traceroute, network scanning, port scanning, TCP checks, and DNS lookup.**

Pure stdlib apart from `certifi` (CA bundle for TLS checks). Linux, macOS & Windows. IPv4 and IPv6.
No root needed for ping, traceroute and MTR on macOS and Linux. Every command returns a meaningful exit code, so it works in scripts and monitoring as well as in your terminal.

```
  ██╗  ██╗██████╗ ██╗███╗   ██╗ ██████╗
  ╚██╗██╔╝██╔══██╗██║████╗  ██║██╔════╝
   ╚███╔╝ ██████╔╝██║██╔██╗ ██║██║  ███╗
   ██╔██╗ ██╔═══╝ ██║██║╚██╗██║██║   ██║
  ██╔╝ ██╗██║     ██║██║ ╚████║╚██████╔╝
  ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═══╝ ╚═════╝
  network diagnostics  ·  beautiful by default
```

Created by **[Mehdi Askari](https://github.com/mehdiaskari)** — see [LICENSE](LICENSE) for attribution terms.

---

## Features

- **Ping** — Live per-packet latency bars, animated spinner, sparkline chart, full statistics
- **Ping --watch** — Continuous live ping with in-place sparkline; Ctrl-C for final summary
- **Traceroute** — Real-time hop-by-hop path with RTT colour coding and summary; `--asn` shows each hop's network operator
- **MTR** — Combined live traceroute + per-hop ping, redraws in place each cycle
- **No root required** — unprivileged ICMP sockets on macOS and Linux for ping, trace and MTR
- **IPv6** — IPv6-only hosts just work; `-4` / `-6` force a family
- **DNS Lookup** — A, AAAA, CNAME, MX, NS, TXT (incl. SPF) with reverse DNS
- **DNS Health Check** — SPF, DMARC (`_dmarc.`), DKIM (common selectors), NS redundancy, MX backup, 0–100 score
- **DNS Propagation** — Compare a record across Google, Cloudflare, Quad9, OpenDNS, AdGuard, Control D and your own resolver
- **Reverse DNS** — PTR lookup with stdlib fallback to 8.8.8.8 for flaky resolvers
- **TCP Connect** — Live TCP port checks with connect timing, success rate, and timeline
- **Port Scanner** — Concurrent TCP port scans with service names and open-port summary
- **IP Scan** — Discover live hosts across CIDR blocks or IP ranges using ICMP echo probes
- **IP Sweep** — Scan CIDR blocks or IP ranges for hosts with open TCP services
- **TLS Inspector** — Certificate details, expiry countdown, cipher, and SAN list
- **HTTP Diagnostics** — Status, headers, redirect chain, TTFB, and total time
- **WHOIS** — Domain registration data via port 43 with automatic RDAP fallback over HTTPS
- **Network Health Score** — 0–100 score combining DNS time, packet loss, latency, and jitter
- **Path MTU Discovery** — Binary-search for the largest unfragmented packet size
- **Saved Profiles** — `xping profile add prod-db 10.0.0.5` then use `xping ping prod-db`
- **Network overview** — `xping net`: interfaces, gateway, DNS servers, public IPv4/IPv6
- **Watch & wait** — `--watch` / `--until-up` on `tcp`, `http` and `health`
- **Exit codes & thresholds** — `--max-loss`, `--max-latency`, `--expect-status`, `--min-days`, `--min-score`, `--quiet`
- **Batch checks** — `xping check checks.toml` runs many checks in parallel with one exit code
- **Speed test** — Multi-connection download/upload via Cloudflare
- **All-in-one** — Run lookup, ping, trace, and TCP checks in a single command
- **Dependency checker** — `xping deps` detects missing tools and shows the correct install command for your distro
- **Machine-readable export** — `--json`, plus `--csv` / `--markdown` as real tables (one row per reply, hop, port, record…)
- **man page included** — `man xping` works after installation

---

## Windows

XPing is a first-class citizen on Windows, and its test suite runs on Windows in CI. TCP, port scan, sweep, HTTP, TLS, DNS and `net` work out of the box with Python 3.10+.

Windows has no unprivileged ICMP sockets, so ping and traceroute use the built-in `ping` / `tracert` (IPv4 and IPv6):

```powershell
pipx install xping
xping ping 1.1.1.1
xping trace cloudflare.com
xping deps
```

`xping deps` prints install hints for missing `ping`, `tracert`, and `dig` when available through winget or chocolatey.

## Installation

### Ubuntu / Debian / Linux Mint / Pop!\_OS — PPA (recommended)

```bash
sudo add-apt-repository ppa:mehdiaskari/xping
sudo apt update
sudo apt install xping
```

Supported: Ubuntu 22.04 LTS, 24.04 LTS, Linux Mint 21+, Pop!\_OS 22.04+

### PyPI (all platforms)

```bash
pipx install xping
```

### From source

```bash
git clone https://github.com/mehdiaskari/xping
cd xping
pip install .
```

### Arch Linux (AUR)

```bash
yay -S python-xping
```

### Tab completion

The Ubuntu/Debian package sets up completion for bash, zsh and fish automatically. With pip, pipx or a source install, run once:

```bash
xping completion --install     # detects your shell; re-run after upgrading
```

It completes commands, options (with descriptions in zsh and fish), option values like `--proto tcp|udp`, hostnames and saved profile names, and `.toml`/`.json` files for `xping check`. To wire it up manually instead, add `source <(xping completion zsh)` to `~/.zshrc`, or `eval "$(xping completion bash)"` to `~/.bashrc` (use `eval` on macOS, whose bash 3.2 ignores `source <(…)`). For fish, run `xping completion fish > ~/.config/fish/completions/xping.fish`. `xping completion --uninstall` removes it.

### Manual page (source installs)

```bash
sudo cp man/xping.1 /usr/share/man/man1/
sudo gzip /usr/share/man/man1/xping.1
sudo mandb
man xping
```

---

## Usage

```
xping <command> <host> [options]
```

### Ping

```bash
xping ping google.com
xping ping 1.1.1.1 -c 10          # 10 packets
xping ping example.com -i 0.2     # 200 ms interval
xping ping host.local -t 5        # 5 s timeout
xping ping google.com --watch     # continuous live mode with sparkline
xping ping -6 google.com          # IPv6
xping ping 1.1.1.1 -c 20 --max-loss 5 --max-latency 100   # exit 1 if exceeded
```

### Traceroute

```bash
xping trace google.com
xping trace 8.8.8.8 --max-hops 15
xping trace example.com --probes 5
xping trace cloudflare.com --asn     # network operator (AS) of every hop
xping trace -6 google.com            # over IPv6
```

### MTR (My Traceroute)

```bash
xping mtr google.com              # combined traceroute + live per-hop ping
xping mtr 1.1.1.1 --cycles 20    # 20 ping cycles per hop
xping mtr example.com --json      # export full hop statistics
xping mtr 1.1.1.1 --asn           # add an AS / operator column
```

### DNS Lookup

```bash
xping lookup github.com
xping lookup github.com --full    # includes TXT records (SPF etc.)
xping dnscheck github.com         # SPF / DMARC / DKIM / NS / MX health check
```

### DNS Propagation

```bash
xping propagation example.com                       # A record on 7 resolvers
xping propagation example.com --type MX
xping propagation example.com --expect 203.0.113.10 # exit 1 until it has propagated
xping propagation example.com --server 10.0.0.53    # add your own resolver
```

Different answers alone don't fail the command (CDNs and geo-DNS vary on purpose). `--expect` turns it into a pass/fail check.

### Reverse DNS

```bash
xping rdns 8.8.8.8               # resolve IP → hostname (PTR record)
xping rdns 1.1.1.1 --json
```

### TCP Connectivity

```bash
xping tcp example.com 443
xping tcp db.internal 5432 -c 5   # 5 connection attempts
xping tcp api.example.com 8443 -t 3 -i 1
xping tcp db.internal 5432 --watch      # live up/down log, uptime summary on Ctrl-C
xping tcp db.internal 5432 --until-up   # wait until the port accepts connections
```

### TLS Inspector

```bash
xping tls github.com              # certificate details and expiry
xping tls example.com --port 8443
xping tls github.com --json
```

### HTTP Diagnostics

```bash
xping http https://example.com    # status, headers, TTFB, redirect chain
xping http http://github.com      # follows redirects automatically
xping http https://api.example.com --json
xping http https://example.com --watch  # watch a website, highlight outages
```

### WHOIS

```bash
xping whois cloudflare.com        # registration data, port 43 + RDAP fallback
xping whois github.com --json
```

### Network Health Score

```bash
xping health google.com           # 0-100 score with actionable findings
xping health 1.1.1.1 -c 16       # more ping packets for better accuracy
xping health example.com --json
```

### Path MTU Discovery

```bash
xping mtu 8.8.8.8                 # find largest unfragmented packet size
xping mtu example.com --max-mtu 9000  # for jumbo frames
```

### Saved Profiles

```bash
xping profile add prod-db 10.0.0.5 --port 5432 --note "Production DB"
xping profile add staging-api staging.example.com
xping profile list
xping profile show prod-db
xping profile remove prod-db

# Use a profile name anywhere a host is expected:
xping ping prod-db
xping tcp prod-db 5432
xping health staging-api
```

### Network Overview

```bash
xping net               # interfaces, gateway, DNS servers, public IPv4/IPv6
xping net --no-public   # skip the public-IP lookup (nothing leaves your network)
xping net --all         # include interfaces with only link-local addresses
```

### Speed Test

```bash
xping speedtest                # 4 parallel connections (default)
xping speedtest -c 1           # single stream (uses less data)
xping speedtest -d 5 --json    # 5-second download phase, JSON output
```

A single stream under-reports fast links. The default uses up to ~40 MB down and 8 MB up.

### Port Scan

```bash
xping portscan example.com
xping portscan example.com --ports 22,80,443
xping portscan 10.0.0.5 --ports 1-1024 -t 0.3 -w 200
```

### IP Scan

```bash
xping ipscan 192.168.1.0/24
xping ipscan 10.0.0.10-10.0.0.50 -t 0.5 -w 128
xping ipscan 172.16.0.0/24 --limit 512
```

### IP Sweep

```bash
xping sweep 192.168.1.0/24
xping sweep 10.0.0.10-10.0.0.50 --ports 22,80,443
xping sweep 172.16.0.0/24 --ports 3389,5985 --limit 512
```

### All at once

```bash
xping all cloudflare.com
xping all example.com --json
```

Runs full DNS lookup, 4-packet ping, traceroute, and TCP checks on ports 443 and 80.

### Export formats

Every diagnostic command accepts structured output flags (interactive rendering is suppressed). Redirect to save to a file:

```bash
xping ping 1.1.1.1 --json
xping trace example.com --csv > hops.csv     # one row per hop, one column per probe
xping lookup github.com --full --markdown
xping all cloudflare.com --json > report.json
```

- `--json` is the complete nested result.
- `--csv` is one row per item (ping reply, hop, port, DNS record, check…), ready for a spreadsheet. Results that are a set of fields (tls, whois, http, health…) export `field,value` rows.
- `--markdown` is a summary table plus one table per section.

### Dependency check

```bash
xping deps
```

## Scripting, exit codes & monitoring

| Exit code | Meaning |
|-----------|---------|
| `0` | The check passed |
| `1` | The check failed: unreachable, closed, HTTP ≥ 400, expired cert, DNS error, a threshold exceeded, or a failed check in a `check` file |
| `2` | Invalid usage or an invalid check file |
| `130` | Interrupted (Ctrl-C) |

Thresholds turn any check into an alarm. Add `-q` / `--quiet` for no output at all:

```bash
xping ping 1.1.1.1 -c 10 --max-loss 10 --max-latency 150 -q || alert "link degraded"
xping tls example.com --min-days 14 -q || echo "renew the certificate"
xping http https://example.com --expect-status 200 --max-latency 800
xping health example.com --min-score 75
xping tcp db.internal 5432 --until-up -q && ./migrate
```

### Batch checks

Put many checks in one file and get one exit code (TOML needs Python 3.11+; JSON works everywhere):

```bash
xping check --example > checks.toml   # commented starter file
xping check checks.toml               # parallel run, pass/fail table
xping check checks.toml --json > report.json
```

```toml
[defaults]
timeout = 3

[[check]]
name = "Database"
type = "tcp"            # ping | tcp | http | tls | lookup | dnscheck | health | propagation
host = "prod-db"        # saved profile names work
port = 5432
max_latency = 50

[[check]]
name = "Certificate"
type = "tls"
host = "example.com"
min_days = 14
```

---

## Permissions

On macOS, and on Linux distributions that allow unprivileged ICMP ("ping") sockets (most current ones do), `ping`, `trace`, `mtr` and `health` work **without root**. Otherwise xping uses raw sockets when run as root, and falls back to the system `ping` / `traceroute` binaries.

`xping deps` shows which mode your system supports. To allow unprivileged ICMP sockets on a Linux box that disables them:

```bash
sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"
```

---

## Environment variables

| Variable      | Effect                                  |
|---------------|-----------------------------------------|
| `NO_COLOR`    | Disable all ANSI colour output          |
| `XPING_DEBUG` | Print full Python tracebacks on errors  |

---

## Contributing

1. Fork and clone the repository
2. `pip install -e ".[dev]"`
3. Make your changes
4. Run `python -m pytest tests/`
5. Open a pull request

---

## License

MIT with Mandatory Attribution — see [LICENSE](LICENSE).

Any fork, derivative work, or redistribution must visibly credit
**Mehdi Askari \<iorganamis@gmail.com\>**.
