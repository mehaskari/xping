# xping

**Beautiful CLI network diagnostics — ping, traceroute, network scanning, port scanning, TCP checks, and DNS lookup.**

Zero external Python dependencies. Pure stdlib. Linux, macOS & Windows.

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
- **Traceroute** — Real-time hop-by-hop path with RTT colour coding and summary
- **MTR** — Combined live traceroute + per-hop ping, redraws in place each cycle
- **DNS Lookup** — A, AAAA, MX, NS, TXT (SPF / DMARC / DKIM) with reverse DNS
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
- **All-in-one** — Run lookup, ping, trace, and TCP checks in a single command
- **Dependency checker** — `xping deps` detects missing tools and shows the correct install command for your distro
- **Machine-readable export** — `--json`, `--csv`, and `--markdown` on every diagnostic command
- **man page included** — `man xping` works after installation

---

## Windows

XPing is a first-class citizen on Windows. TCP, port scan, sweep, and DNS fallback work out of the box with Python 3.10+.

For ICMP ping and traceroute, install the built-in optional tools or let xping use subprocess fallbacks:

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
sudo apt install python3-xping
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
```

### Traceroute

```bash
xping trace google.com
xping trace 8.8.8.8 --max-hops 15
xping trace example.com --probes 5
```

### MTR (My Traceroute)

```bash
xping mtr google.com              # combined traceroute + live per-hop ping
xping mtr 1.1.1.1 --cycles 20    # 20 ping cycles per hop
xping mtr example.com --json      # export full hop statistics
```

### DNS Lookup

```bash
xping lookup github.com
xping lookup github.com --full    # includes TXT / SPF / DMARC / DKIM
```

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

Every diagnostic command accepts structured output flags (interactive rendering is suppressed):

```bash
xping ping 1.1.1.1 --json
xping trace example.com --csv
xping lookup github.com --full --markdown
xping all cloudflare.com --json
```

### Dependency check

```bash
xping deps
```

---

## Permissions

ICMP raw sockets require root or `cap_net_raw`. Without them xping
automatically falls back to the system `ping` / `traceroute` binaries.

Grant capability without running as root:

```bash
sudo setcap cap_net_raw+ep $(which xping)
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
