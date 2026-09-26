# xping User Guide

The complete guide to **xping**, a network diagnostics toolkit for the
terminal. This guide explains every command and option, shows what the
output means, and walks through common tasks.

> **Quick reference:** `xping --help` lists every command, and
> `xping <command> --help` lists a command's options. `man xping` has the
> same material as a manual page. This guide adds explanations,
> background and recipes.

---

## Contents

1. [Introduction](#1-introduction)
2. [Installation](#2-installation)
3. [Core concepts](#3-core-concepts)
   - [Command structure](#31-command-structure)
   - [Hosts, profiles and address families](#32-hosts-profiles-and-address-families)
   - [Output: interactive, JSON, CSV, Markdown, quiet](#33-output-interactive-json-csv-markdown-quiet)
   - [Exit codes and thresholds](#34-exit-codes-and-thresholds)
   - [Watch mode and alerts](#35-watch-mode-and-alerts)
   - [Permissions (why no root is needed)](#36-permissions-why-no-root-is-needed)
   - [Personal defaults (config file)](#37-personal-defaults-config-file)
4. [Command reference](#4-command-reference)
   - Troubleshooting: [`doctor`](#xping-doctor) · [`net`](#xping-net) · [`health`](#xping-health) · [`all`](#xping-all)
   - Reachability and paths: [`ping`](#xping-ping) · [`trace`](#xping-trace) · [`mtr`](#xping-mtr) · [`tcp`](#xping-tcp) · [`udp`](#xping-udp) · [`mtu`](#xping-mtu)
   - DNS and domains: [`lookup`](#xping-lookup) · [`rdns`](#xping-rdns) · [`dnscheck`](#xping-dnscheck) · [`blocklist`](#xping-blocklist) · [`propagation`](#xping-propagation) · [`whois`](#xping-whois)
   - Web and TLS: [`http`](#xping-http) · [`tls`](#xping-tls)
   - Scanning: [`portscan`](#xping-portscan) · [`sweep`](#xping-sweep) · [`ipscan`](#xping-ipscan) · [`osdetect`](#xping-osdetect)
   - Local machine: [`listen`](#xping-listen) · [`ntp`](#xping-ntp) · [`speedtest`](#xping-speedtest)
   - Automation: [`check`](#xping-check) · [`diff`](#xping-diff) · [`profile`](#xping-profile)
   - Utilities: [`config`](#xping-config) · [`completion`](#xping-completion) · [`deps`](#xping-deps) · [`about`](#xping-about)
5. [Batch check files](#5-batch-check-files)
6. [Recipes](#6-recipes)
7. [Files, environment and privacy](#7-files-environment-and-privacy)
8. [Platform notes](#8-platform-notes)
9. [Troubleshooting and FAQ](#9-troubleshooting-and-faq)

---

## 1. Introduction

xping bundles the tools people usually juggle when a network misbehaves:
`ping`, `traceroute`, `mtr`, `dig`, `whois`, `curl -w`, `openssl s_client`,
`nmap`-style scans and more. They sit behind one consistent command line
with readable, colour-coded output.

What it is designed around:

- **Answers, not just numbers.** `xping doctor` tells you *why* the
  internet is down, `health` turns loss, latency and jitter into a score,
  and `dnscheck` grades a domain's mail setup.
- **No root.** ICMP uses unprivileged sockets on macOS and Linux;
  even TCP traceroute works as a normal user.
- **Scriptable.** Every command returns a meaningful exit code. Thresholds
  turn any check into an alarm, and `--json` / `--csv` / `--markdown`
  export the full result.
- **Small footprint.** Pure Python standard library plus `certifi`. Where
  it helps, system tools (`ping`, `traceroute`, `dig`, `ss`) are used as
  fallbacks, but none are required.

xping runs on Linux, macOS and Windows with Python 3.10 or newer.

---

## 2. Installation

| Platform | Command |
|----------|---------|
| Ubuntu 24.04, Linux Mint 22, Pop!_OS 24.04 | `sudo add-apt-repository ppa:mehdiaskari/xping && sudo apt update && sudo apt install xping` |
| Any Linux with snapd | `sudo snap install xping` (newest builds: `--edge`) |
| macOS, Windows, any Linux | `pipx install xping` (or `pip install xping`) |
| From source | `git clone https://github.com/mehaskari/xping && cd xping && pip install .` |

**Upgrading:** `sudo apt upgrade`, `sudo snap refresh xping`, or
`pipx upgrade xping`.

**Tab completion.** The PPA package installs completion for bash, zsh
and fish. With pip, pipx or a source install, run this once, and again
after each upgrade:

```bash
xping completion --install
```

See [`xping completion`](#xping-completion) for details.

**Check the setup.** `xping deps` shows which optional system tools are
present and how to install missing ones. `xping --version` prints the
version.

---

## 3. Core concepts

### 3.1 Command structure

```
xping <command> [arguments] [options]
xping <host>                      # shorthand: ping the host, then suggest next steps
```

Options can come before or after the arguments. Short and long forms are
equivalent (`-c 10` = `--count 10`). Running `xping` alone prints the
banner and the command list.

The shorthand `xping 8.8.8.8` sends five pings. In an interactive
terminal it then lists other commands worth running for that host.

### 3.2 Hosts, profiles and address families

Anywhere a command expects a **host**, you can give:

- a hostname (`github.com`),
- an IPv4 or IPv6 address (`1.1.1.1`, `2606:4700:4700::1111`),
- a **saved profile name** (`prod-db`). See [`profile`](#xping-profile).

**IPv4 and IPv6.** By default xping resolves a name to IPv4 if it can,
and uses IPv6 when the name has no IPv4 address. IPv6-only hosts
therefore just work. To force a family, use:

| Option | Effect |
|--------|--------|
| `-4`, `--ipv4` | Use IPv4 only |
| `-6`, `--ipv6` | Use IPv6 only |

These options are available on `ping`, `trace`, `mtr`, `tcp`, `udp`, `ntp`,
`portscan`, `tls`, `http`, `health`, `mtu`, `osdetect` and `all`.

### 3.3 Output: interactive, JSON, CSV, Markdown, quiet

Every diagnostic command accepts exactly one of these output options:

| Option | Output |
|--------|--------|
| *(none)* | Interactive, colour-coded view with live progress |
| `--json` | The complete result as nested JSON |
| `--csv` | One row per item (ping reply, hop, port, DNS record, check, doctor step…) |
| `--markdown` | A summary table plus one table per section, ready for tickets and reports |
| `-q`, `--quiet` | No output at all: the result is only the [exit code](#34-exit-codes-and-thresholds) |

```bash
xping trace example.com --csv > hops.csv
xping all cloudflare.com --json > report.json
xping lookup github.com --full --markdown >> incident.md
```

Results that are a set of fields rather than a list (`tls`, `whois`,
`http`, `health`, `net`…) export CSV as `field,value` rows.

Colours are turned off automatically when output is not a terminal, or
when the `NO_COLOR` environment variable is set.

### 3.4 Exit codes and thresholds

Every command reports its verdict through the exit code, so it works
directly in scripts, cron jobs, CI pipelines and monitoring systems.

| Code | Meaning |
|------|---------|
| `0` | The check passed |
| `1` | The check failed: unreachable host, closed port, HTTP ≥ 400, expired certificate, DNS error, a threshold exceeded, a failed step in `doctor`, or a failed entry in a `check` file |
| `2` | Invalid usage (unknown option, bad value, invalid check file) |
| `130` | Interrupted with Ctrl-C |

**Thresholds** turn a measurement into a pass/fail check:

| Threshold | Commands | Fails when |
|-----------|----------|------------|
| `--max-loss PCT` | `ping`, `mtr` | packet loss (at the destination, for `mtr`) is above PCT % |
| `--max-latency MS` | `ping`, `mtr`, `tcp`, `udp`, `http` | average RTT / connect time / reply time / total request time is above MS |
| `--max-offset MS` | `ntp` | the system clock differs from the NTP server by more than MS |
| `--expect-status CODE` | `http` | the final status is not CODE (without it, any status ≥ 400 fails) |
| `--min-days N` | `tls` | the certificate expires in fewer than N days |
| `--min-score N` | `health`, `dnscheck` | the 0–100 score is below N |
| `--expect VALUE` | `propagation` | any answering resolver does not return VALUE |

When a threshold fails, the reason is printed on stderr (unless you used
`--quiet`):

```bash
xping ping 1.1.1.1 -c 10 --max-loss 10 --max-latency 150 -q || echo "link degraded"
xping tls example.com --min-days 14 -q || echo "renew the certificate"
```

### 3.5 Watch mode and alerts

`tcp`, `udp`, `http` and `health` can repeat themselves:

| Option | Effect |
|--------|--------|
| `--watch` | Repeat every `--every` seconds until Ctrl-C. Prints one line per check, highlights DOWN/UP changes with the downtime, and ends with a summary (uptime %, state changes, longest outage, average latency). The exit code reflects the final state. |
| `--until-up` | Repeat until the check passes, then exit 0. Combine with `-q` to wait silently in scripts. Ctrl-C exits 130. |
| `--every SEC` | Seconds between checks. Defaults: `tcp` 2, `udp` 5, `http` 5, `health` 30. |

Each round is judged exactly like a single run. Thresholds such as
`--max-latency` or `--expect-status` therefore decide UP and DOWN too.

`ping --watch` (`-w`) is a separate live mode. It shows a continuously
redrawn sparkline and running statistics.

**Alerts.** In any watch mode (`ping --watch`, and `--watch` /
`--until-up` on `tcp`, `udp`, `http`, `health`) you can be told about changes:

| Option | Effect |
|--------|--------|
| `--notify` | Desktop notification on every DOWN/UP change: Notification Center on macOS, `notify-send` on Linux, the terminal bell elsewhere |
| `--webhook URL` | POST one JSON event per change to URL (http or https) |

Rules:

- The first check only sets the baseline. After that, every change fires
  an event, and the UP message includes how long the outage lasted.
- `--until-up` always announces the final UP, even when the first check
  already succeeds.
- `ping --watch` counts a host as down only after **three lost pings in a
  row**, so a single dropped packet is not an outage.
- Webhooks are sent in the background, so a slow endpoint never delays
  checks. A failing endpoint is reported once and never stops the watch.

The webhook body works with Slack, Mattermost and Google Chat (which
read `text`) and with Discord (which reads `content`) without any
adapter. Other receivers can use the structured fields:

```json
{
  "source": "xping",
  "event": "down",
  "target": "db.local:5432",
  "check": "tcp",
  "detail": "db.local:5432 refused or timed out on every attempt",
  "latency_ms": null,
  "time": "2026-09-26T09:40:12+00:00",
  "machine": "laptop",
  "text": "🔴 xping: db.local:5432 (tcp) is DOWN — db.local:5432 refused or timed out on every attempt",
  "content": "🔴 xping: db.local:5432 (tcp) is DOWN — …"
}
```

Using `--notify` or `--webhook` outside watch mode is a usage error
(exit 2). Export formats cannot be combined with watch mode.

### 3.6 Permissions (why no root is needed)

- **ICMP** (`ping`, `trace`, `mtr`, `health`, `doctor`): unprivileged
  "ping sockets". These are always available on macOS, and on Linux when
  your group is inside `net.ipv4.ping_group_range`, which is the default
  on current distributions. When running as root, raw sockets are used.
  The last fallback is the system `ping` / `traceroute`.
- **TCP traceroute** (`trace --tcp`): an ordinary TCP socket. On Linux
  the router's reply is read from the socket's error queue; on macOS it
  is read from an unprivileged ICMP socket.
- **Windows** has no unprivileged ICMP sockets, so it uses the built-in
  `ping` and `tracert`.

To enable ping sockets on a Linux system that disables them:

```bash
sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"
```

`xping deps` shows which mode your system uses.

### 3.7 Personal defaults (config file)

Options you always type can live in `~/.xping/config.toml`:

```toml
[defaults]            # every command that has the option
timeout = 3
ipv4 = true

[ping]                # one command
count = 10
interval = 0.2

[lookup]
doh = "cloudflare"

[ntp]
server = "time.cloudflare.com"   # optional positional arguments work too
```

- **Keys** are long option names, written as `max-latency` or
  `max_latency`. Flags take `true` / `false`. Repeatable options take a
  list, e.g. `server = ["9.9.9.9"]`.
- **The command line always wins.** `xping ping host -c 3` sends 3
  packets even with `count = 10`. When you use one option of an either/or
  pair on the command line, the file's value for the other is dropped: `-6`
  beats `ipv4 = true`, and `--server` beats `doh = …`.
- **Mistakes are errors, not silent no-ops.** An unknown section, an
  unknown option or a bad value stops xping with exit code 2 and names the
  file, section and key. `xping config` still works then, and shows what
  is wrong.
- **Scope.** The file applies to commands and to the `xping HOST`
  shorthand (via `[ping]`). It does not apply to `check` files, which have
  their own `[defaults]`.
- **Switching it off.** `XPING_CONFIG=/path/to/file` uses another file,
  and `XPING_CONFIG=none` ignores the config for one run. A flag set to
  `true` in the file cannot be switched off on the command line; use
  `XPING_CONFIG=none` for that.
- TOML config files need Python 3.11+.

Start from the commented example with
`xping config --example > ~/.xping/config.toml`. Then check what is
active with [`xping config`](#xping-config).

---

## 4. Command reference

Each entry lists the synopsis, what the command does, its options with
defaults, and examples. The [output options](#33-output-interactive-json-csv-markdown-quiet)
(`--json`, `--csv`, `--markdown`, `-q`) work on every diagnostic command
and are not repeated below.

---

### Troubleshooting

#### `xping doctor`

```
xping doctor [HOST] [--port PORT]
```

Answers the question **"why is my internet not working?"**. It walks
outward from your machine and stops guessing as soon as something breaks:

| # | Step | How it is checked | What a failure means |
|---|------|-------------------|----------------------|
| 1 | Network interface | an interface has a usable (non link-local) address | not connected, or `169.254.x.x` = DHCP failed |
| 2 | Default gateway | a default route exists; the router is pinged | no router; no reply is only a *warning* (many routers ignore ping) |
| 3 | Internet (by IP) | TCP 443 to 1.1.1.1, 8.8.8.8 and 9.9.9.9 — no DNS involved | no internet behind the router |
| 4 | DNS | the system resolver looks up `cloudflare.com` / `google.com`. If that fails, a direct query to 1.1.1.1 follows | "your DNS server is broken" vs. "DNS traffic is blocked" |
| 5 | Connection quality | 5 pings to 1.1.1.1 | ≥ 20 % loss or > 300 ms average is a *warning* |
| 6 | Captive portal | `captive.apple.com` must answer "Success" | a Wi-Fi login page is intercepting traffic |
| 7 | HTTPS | verified TLS request to `www.cloudflare.com` | HTTPS is intercepted (proxy, antivirus). The server timestamp also reveals a system clock that is off by more than 2 minutes (*warning*) |
| 8 | IPv6 | global IPv6 address and a TCP connection to Cloudflare over IPv6 | informational only, never a failure |
| 9 | Target *(optional)* | resolve HOST and connect to `--port` | the internet works; HOST itself is down or blocking you |

Steps that depend on a failed step are shown as skipped. The run ends
with a single plain-language diagnosis and what to do about it, for
example:

```
  ✘ The router works, but there is no internet behind it.
    Restart the modem/router; if that does not help, the problem is with your ISP.
```

| Option | Default | Description |
|--------|---------|-------------|
| `HOST` | — | Optional host to test after the basics |
| `--port PORT` | 443 | TCP port to test on HOST |

Exit code 1 when any step fails; warnings alone keep exit code 0. A full
run takes about 5 seconds because independent steps run in parallel.

```bash
xping doctor
xping doctor github.com
xping doctor db.example.com --port 5432
xping doctor --json | jq '.steps[] | select(.status != "ok")'
```

#### `xping net`

```
xping net [--no-public] [--all]
```

Your own network at a glance:

- hostname
- the local IPv4/IPv6 source addresses the OS uses for outbound traffic
- default gateways (with the interface)
- DNS servers. With systemd-resolved, the real upstream servers are shown
  behind the `127.0.0.53` stub.
- public IPv4/IPv6 addresses as seen from the internet, with the country
  and the Cloudflare data centre that answered
- a table of interfaces with state, MTU and addresses

| Option | Description |
|--------|-------------|
| `--no-public` | Skip the public IP lookup. Nothing leaves your network. |
| `--all` | Also list interfaces that only have link-local addresses |

Data sources: `ip` and `/etc/resolv.conf` on Linux; `ifconfig`, `route`
and `scutil --dns` on macOS; `ipconfig /all` on Windows. The public
address comes from `https://1.1.1.1/cdn-cgi/trace`.

```bash
xping net
xping net --no-public --json
```

#### `xping health`

```
xping health HOST [-c N] [-t SEC] [--min-score N] [--watch | --until-up] [--every SEC]
```

Measures DNS resolve time, packet loss, average latency and jitter, and
combines them into a **0–100 Network Health Score**:

| Factor | Penalty |
|--------|---------|
| Packet loss | 0.6 points per % (max 50). 100 % loss = score 0 |
| Average latency | ≥ 30 ms: −5 · ≥ 100 ms: −15 · ≥ 300 ms: −25 |
| Jitter | ≥ 10 ms: −5 · ≥ 30 ms: −10 · ≥ 80 ms: −15 |
| DNS resolve time | ≥ 150 ms: −5 · ≥ 400 ms: −10 |

| Grade | Score |
|-------|-------|
| Excellent | 90–100 |
| Good | 75–89 |
| Fair | 50–74 |
| Poor | 25–49 |
| Critical | 0–24 |

Every run is saved to `~/.xping/health_history.json` (the last 50 per
host). The history and a trend arrow are shown each time. Findings are
explained in plain words, for example "Jitter is high — voice/video calls
will sound choppy".

| Option | Default | Description |
|--------|---------|-------------|
| `-c`, `--count N` | 8 | Ping packets used for scoring |
| `-t`, `--timeout SEC` | 2.0 | Per-packet timeout |
| `--min-score N` | — | Exit 1 if the score is below N |
| `--watch`, `--until-up`, `--every SEC`, `--notify`, `--webhook URL` | every: 30 | [Watch mode and alerts](#35-watch-mode-and-alerts) |
| `-4`, `-6` | — | Address family |

```bash
xping health google.com
xping health vpn.example.com --min-score 75 -q
xping health 1.1.1.1 --watch --every 60 --notify
```

#### `xping all`

```
xping all HOST [-4 | -6]
```

A full diagnostic bundle in one command:

1. `lookup --full` (all DNS records)
2. `ping` (4 packets)
3. `trace`
4. `tcp` on ports 443 and 80 (2 attempts each)

It ends with a one-page summary. It fails when DNS fails, the host does
not answer ping, or neither port 443 nor 80 accepts a connection.
`--json` gives one report containing every part.

| Option | Description |
|--------|-------------|
| `-4`, `-6` | Address family for ping, trace and TCP |

```bash
xping all cloudflare.com
xping all example.com --json > report.json
```

---

### Reachability and paths

#### `xping ping`

```
xping ping HOST [-c N] [-t SEC] [-i SEC] [--watch] [--max-loss PCT] [--max-latency MS]
```

Sends ICMP echo requests. Each reply is printed immediately with a
colour-coded latency bar. The summary shows sent/received counts, loss,
min/avg/max RTT, jitter, a sparkline and a latency histogram.

Latency colours, used everywhere in xping: **green** < 30 ms,
**amber** < 100 ms, **yellow** < 300 ms, **red** ≥ 300 ms.

| Option | Default | Description |
|--------|---------|-------------|
| `-c`, `--count N` | 5 | Number of packets |
| `-t`, `--timeout SEC` | 2.0 | Per-packet timeout |
| `-i`, `--interval SEC` | 0.5 | Interval between packets |
| `-w`, `--watch` | — | Continuous live mode with an in-place sparkline (Ctrl-C to stop) |
| `--notify`, `--webhook URL` | — | [Alerts](#35-watch-mode-and-alerts) in watch mode (down = 3 lost pings in a row) |
| `--max-loss PCT` | — | Exit 1 if packet loss is above PCT % |
| `--max-latency MS` | — | Exit 1 if the average RTT is above MS |
| `-4`, `-6` | — | Address family |

Exit code 1 when the host cannot be resolved or answers no ping at all.

```bash
xping ping 1.1.1.1
xping ping google.com -c 20 -i 0.2
xping ping router.local --watch --notify
xping ping 8.8.8.8 -c 10 --max-loss 5 -q
```

#### `xping trace`

```
xping trace HOST [-m N] [-t SEC] [-p N] [--asn] [--tcp] [--port PORT]
```

Shows the path packets take to HOST, one line per router ("hop"), printed
as each answer arrives. The summary says whether the destination was
reached, how many hops answered, and the final hop's RTT.

A hop shown as `* * *` did not answer. That is common and usually
harmless: many routers do not reply to probes but still forward traffic.
It only matters when *every* hop after some point stays silent.

**TCP mode (`--tcp`).** Firewalls often drop ICMP, and then a normal
traceroute ends in `* * *` halfway. With `--tcp`, each probe is a TCP
connection attempt (SYN) to a port the service really serves:

- routers still answer an expiring TTL with ICMP "time exceeded";
- the destination answers with SYN-ACK (open) or RST (closed), and either
  counts as reached.

No root is needed on Linux or macOS. TCP mode is not available on Windows.

| Option | Default | Description |
|--------|---------|-------------|
| `-m`, `--max-hops N` | 30 | Maximum number of hops |
| `-t`, `--timeout SEC` | 2.0 | Per-hop timeout |
| `-p`, `--probes N` | 3 | Probes per hop |
| `--asn` | — | Show each hop's network operator (AS number and name) via Team Cymru DNS. Opt-in, because hop addresses are sent to Cymru. |
| `-T`, `--tcp` | — | Probe with TCP SYNs instead of ICMP |
| `--port PORT` | 443 | TCP port for `--tcp` (implies `--tcp`) |
| `-4`, `-6` | — | Address family |

```bash
xping trace 1.1.1.1
xping trace cloudflare.com --asn
xping trace example.com --tcp
xping trace git.example.com --port 22
xping trace example.com --csv > hops.csv
```

#### `xping mtr`

```
xping mtr HOST [-c N] [-m N] [-t SEC] [-i SEC] [--asn] [--max-loss PCT] [--max-latency MS]
```

"My traceroute": discovers the path once, then pings every hop repeatedly
and redraws a live table. For each hop it shows loss %, last/average/best/
worst RTT, standard deviation and a sparkline.

How to read it: loss at an intermediate hop that does **not** continue to
later hops is just that router rate-limiting its replies. Loss that starts
at one hop and continues all the way to the destination points to a real
problem at that hop.

| Option | Default | Description |
|--------|---------|-------------|
| `-c`, `--cycles N` | 10 | Ping cycles per hop |
| `-m`, `--max-hops N` | 30 | Maximum number of hops |
| `-t`, `--timeout SEC` | 2.0 | Per-probe timeout |
| `-i`, `--interval SEC` | 0.3 | Interval between cycles |
| `--asn` | — | AS number/operator column (Team Cymru DNS) |
| `--max-loss PCT` | — | Exit 1 if loss **at the destination** is above PCT % |
| `--max-latency MS` | — | Exit 1 if the destination's average RTT is above MS |
| `-4`, `-6` | — | Address family |

```bash
xping mtr 1.1.1.1 --cycles 30
xping mtr example.com --asn --max-loss 2
```

#### `xping tcp`

```
xping tcp HOST PORT [-c N] [-t SEC] [-i SEC] [--max-latency MS] [--watch | --until-up] [--every SEC]
```

Opens TCP connections to HOST:PORT and reports each attempt (open or
failed, with the connect time). The summary shows the success rate and
min/avg/max connect times. This is the simplest way to answer "is the
service listening, and is the firewall letting me through?".

| Option | Default | Description |
|--------|---------|-------------|
| `-c`, `--count N` | 3 | Connection attempts |
| `-t`, `--timeout SEC` | 2.0 | Per-attempt timeout |
| `-i`, `--interval SEC` | 0.5 | Interval between attempts |
| `--max-latency MS` | — | Exit 1 if the average connect time is above MS |
| `--watch`, `--until-up`, `--every SEC`, `--notify`, `--webhook URL` | every: 2 | [Watch mode and alerts](#35-watch-mode-and-alerts) |
| `-4`, `-6` | — | Address family |

Exit code 1 when every attempt is refused or times out.

```bash
xping tcp example.com 443
xping tcp db.internal 5432 --until-up -q && ./run-migrations
xping tcp prod-db 5432 --watch --webhook https://hooks.slack.com/services/…
```

#### `xping udp`

```
xping udp HOST PORT [-c N] [-t SEC] [-i SEC] [--probe KIND] [--payload HEX] [--max-latency MS] [--watch | --until-up]
```

Checks whether a UDP service answers. UDP has no handshake, so the only
proof that a service is there is a reply. xping therefore sends a request
the service understands and classifies each attempt:

| State | Meaning |
|-------|---------|
| **open** | a reply came back — the service is there |
| **closed** | the host answered ICMP "port unreachable" — nothing listens on that port |
| **no response** | nothing came back: the port is filtered by a firewall, **or** the service ignored the request. UDP cannot tell these apart. |

The request is chosen by port (`--probe auto`), or set explicitly:

| Probe | Sends | Default for port |
|-------|-------|------------------|
| `dns` | a root `NS` query | 53, 5353 |
| `ntp` | an SNTP client request | 123 |
| `snmp` | SNMPv2c GET `sysDescr.0` with community `public` | 161 |
| `empty` | an empty datagram | everything else |

| Option | Default | Description |
|--------|---------|-------------|
| `-c`, `--count N` | 3 | Probes to send |
| `-t`, `--timeout SEC` | 2.0 | Seconds to wait for each reply |
| `-i`, `--interval SEC` | 0.5 | Interval between probes |
| `--probe KIND` | auto | `auto`, `dns`, `ntp`, `snmp` or `empty` |
| `--payload HEX` | — | Send these bytes instead, e.g. `--payload "de ad be ef"` |
| `--max-latency MS` | — | Exit 1 if the average reply time is above MS |
| `--watch`, `--until-up`, `--every SEC`, `--notify`, `--webhook URL` | every: 5 | [Watch mode and alerts](#35-watch-mode-and-alerts) |
| `-4`, `-6` | — | Address family |

Exit code 0 only when a reply came back; *closed* and *no response* both
exit 1.

```bash
xping udp 1.1.1.1 53                   # is this DNS server answering?
xping udp time.example.com 123
xping udp switch.lan 161               # SNMP agent with community "public"?
xping udp game.example.com 27015 --payload "ffffffff54536f7572636520456e67696e6520517565727900"
xping udp dns.internal 53 --watch --notify
```

#### `xping mtu`

```
xping mtu HOST [--max-mtu BYTES] [-t SEC]
```

Finds the **path MTU**, the largest packet that reaches HOST without
being fragmented. It binary-searches with "don't fragment" pings. A path
MTU below 1500 is typical of VPNs, PPPoE (1492) and tunnels. When large
transfers hang but small requests work, an MTU problem is a likely cause.

| Option | Default | Description |
|--------|---------|-------------|
| `--max-mtu BYTES` | 1500 | Upper bound of the search |
| `-t`, `--timeout SEC` | 2.0 | Per-probe timeout |
| `-4`, `-6` | — | Address family (IPv6 on Linux/macOS; macOS needs root for it) |

```bash
xping mtu 8.8.8.8
xping mtu vpn-gateway.example.com --max-mtu 1600
```

---

### DNS and domains

#### `xping lookup`

```
xping lookup HOST [--full] [--server IP | --doh PROVIDER]
```

Queries DNS records:

- A and AAAA
- CNAME
- MX (with priorities)
- NS
- with `--full`, TXT (SPF and other verification records)

Every address found is also reverse-resolved. It uses `dig` when it is
installed; otherwise xping sends its own UDP DNS queries.

**DNS over HTTPS (`--doh`).** The queries go encrypted, over HTTPS
(RFC 8484), to a DoH resolver instead of plain DNS on port 53. Use it when
your network's resolver filters, rewrites or hijacks answers: compare
`xping lookup NAME` with `xping lookup NAME --doh cloudflare`. Different
answers mean something on the way is interfering. Some networks block
the DoH services themselves; the queries then fail with `TIMEOUT`.

| Provider | URL |
|----------|-----|
| `cloudflare` | `https://cloudflare-dns.com/dns-query` |
| `google` | `https://dns.google/dns-query` |
| `quad9` | `https://dns.quad9.net/dns-query` |
| any `https://…` URL | your own or another DoH server |

| Option | Description |
|--------|-------------|
| `-f`, `--full` | Include TXT records |
| `-s`, `--server IP` | Ask this resolver instead of the system one (like `dig @8.8.8.8`) |
| `--doh PROVIDER` | Query over DNS-over-HTTPS: `cloudflare`, `google`, `quad9`, or a URL. Cannot be combined with `--server`. |

DMARC and DKIM live under other names; use [`dnscheck`](#xping-dnscheck)
for them.

```bash
xping lookup github.com
xping lookup example.com --full --server 1.1.1.1
xping lookup example.com --doh cloudflare      # encrypted, bypasses the local resolver
xping lookup example.com --doh https://dns.example.net/dns-query
```

#### `xping rdns`

```
xping rdns IP
```

Reverse DNS (PTR) lookup. It asks the system resolver first. If that
finds no PTR record, it queries 8.8.8.8 directly.

```bash
xping rdns 8.8.8.8
```

#### `xping dnscheck`

```
xping dnscheck DOMAIN [--min-score N]
```

A DNS and e-mail health check with a 0–100 score:

| Check | Pass | Warning / failure |
|-------|------|-------------------|
| A record | an IPv4 address exists | fail: none |
| AAAA record | IPv6 exists | info only: IPv6 is recommended, not required |
| NS redundancy | ≥ 2 nameservers | warn: a single nameserver is a single point of failure |
| MX records | ≥ 2 mail servers | warn: no backup MX · info: no MX (fine for non-mail domains) |
| SPF | exactly one record, `-all` | warn: `~all` (softfail) · fail: `+all`, several SPF records, or none |
| DMARC | `p=reject` at `_dmarc.DOMAIN` | warn: `quarantine` or `none` · fail: missing |
| DKIM | a key at a common selector | info only: selectors cannot be listed, so "not found" is not a failure |
| DNSSEC | signed, a DS record at the parent, and the answer validates | fail: signatures are broken ("bogus"), so validating resolvers cannot resolve the domain · warn: signed but no DS at the parent (not active) · info: not signed |

DNSSEC is checked with three queries to a validating resolver
(Cloudflare 1.1.1.1, falling back to Google 8.8.8.8), with the DNSSEC
"DO" flag set:

1. the domain's **DS** record at the parent, which shows whether DNSSEC
   is switched on at the registrar;
2. its **SOA**: are the answers signed (RRSIG), and did the resolver
   validate them (the AD flag)?
3. when that fails with SERVFAIL, the SOA again with "checking disabled".
   If it then works, the signatures are broken.

The DKIM selectors tried are `default`, `google`, `selector1`, `selector2`,
`k1`, `k2`, `dkim`, `mail`, `s1` and `s2`. Checks whose DNS query failed
(SERVFAIL, timeout) are marked "not verified" and left out of the score.
Grades: Excellent ≥ 90, Good ≥ 70, Fair ≥ 50, Poor ≥ 25, Critical below.

| Option | Description |
|--------|-------------|
| `--min-score N` | Exit 1 if the score is below N |

```bash
xping dnscheck example.com
xping dnscheck mycompany.com --min-score 80 -q
```

#### `xping blocklist`

```
xping blocklist IP|DOMAIN [--zone ZONE]... [-t SEC] [--all]
```

Checks whether an IP address or a domain's mail servers are on a spam
**blocklist** (DNSBL). Many mail servers reject mail from listed
addresses, so this is the first thing to check when e-mail bounces or
lands in spam.

- **For an IPv4 address**, xping checks it on the IP lists.
- **For a domain**, it checks the domain on the domain lists, and the
  IPv4 addresses of its mail servers (MX) and web host (A) on the IP
  lists, up to 6 addresses. IPv6 addresses are shown but not checked,
  because few lists support them.

| IP lists | Domain lists |
|----------|--------------|
| Spamhaus ZEN, SpamCop, Barracuda, PSBL, Mailspike, UCEPROTECT L1, DroneBL, s5h | Spamhaus DBL, SURBL, URIBL |

How it works: to check 192.0.2.10 against `zen.spamhaus.org`, xping looks
up `10.2.0.192.zen.spamhaus.org`. An answer in `127.0.0.0/8` means
*listed*, and the last number says why; "does not exist" means *not
listed*. Each result is one of:

| Status | Meaning |
|--------|---------|
| ✘ **listed** | on the list — the Details column explains why when the list says (e.g. Spamhaus SBL = spam source, XBL = infected host) |
| ℹ **policy** | Spamhaus PBL only: an end-user address range. Normal for home and mobile connections; a problem only for a mail server, which should not send from such a range |
| ✔ **clean** | not listed |
| ? **refused** | the list refused to answer. Spamhaus and URIBL refuse queries that arrive via big public resolvers (8.8.8.8, 1.1.1.1); use your ISP's or your own resolver |
| ? **error** | the lookup timed out or failed |

The output is a summary with one row per checked address or domain,
e.g. "clean on 8/8 IP lists". Every result that is not *clean* is also
shown in full below it. `--all` prints every list for every address
instead. The last line counts the checks, e.g. "43 checks on 11 lists":
11 lists, some of them checked for several addresses.

| Option | Default | Description |
|--------|---------|-------------|
| `--zone ZONE` | — | Also check this DNSBL zone (repeatable) |
| `-t`, `--timeout SEC` | 5 | Seconds to wait per lookup |
| `--all` | — | Show every list for every address, not the summary |

Exit code 1 when the target is **listed** on any list, or when nothing
could be checked. *Policy*, *refused* and *error* results do not fail.

Queries go through your system resolver to each list's DNS servers, so
the list operators see which address or domain you checked.

```bash
xping blocklist 203.0.113.25
xping blocklist mycompany.com          # the domain, plus its mail and web servers
xping blocklist 203.0.113.25 --zone bl.example.org
xping blocklist mail.mycompany.com -q || echo "we are on a blocklist"
```

#### `xping propagation`

```
xping propagation NAME [--type TYPE] [--expect VALUE]... [--server IP]... [--no-system]
```

After you change a DNS record, resolvers keep serving the old value until
its TTL expires. `propagation` asks your own resolver plus Google,
Cloudflare, Quad9, OpenDNS, AdGuard and Control D in parallel. It shows
which answers differ from the majority.

Different answers alone do **not** fail the command, because CDNs and
geo-DNS return different addresses on purpose. `--expect` turns the
command into a pass/fail check.

| Option | Default | Description |
|--------|---------|-------------|
| `-t`, `--type TYPE` | A | Record type: A, AAAA, CNAME, MX, NS or TXT |
| `--expect VALUE` | — | Exit 1 unless every answering resolver returns VALUE. Repeatable. Write MX as `"PRIO HOST"`. |
| `-s`, `--server IP` | — | Also query this resolver (repeatable) |
| `--no-system` | — | Skip your own system resolver |

```bash
xping propagation example.com
xping propagation example.com --type MX
xping propagation www.example.com --expect 203.0.113.10 -q && echo "propagated"
```

#### `xping whois`

```
xping whois DOMAIN
```

Shows domain registration data: registrar, creation and expiry dates,
status codes and name servers. It queries WHOIS on port 43, following
referrals from IANA to the registry to the registrar, and retries each
server. When port 43 is blocked it falls back to **RDAP** over HTTPS.

```bash
xping whois cloudflare.com
```

---

### Web and TLS

#### `xping http`

```
xping http URL [-t SEC] [--expect-status CODE] [--max-latency MS] [--watch | --until-up] [--every SEC]
```

Sends an HTTP GET and follows redirects (up to 10; a redirect loop is
detected). A URL without a scheme gets `http://`. The report has these
sections:

- **Status** and the **redirect chain**.
- **Timing waterfall** for the final request, each phase measured on its
  own, like `curl -w` or a browser's network tab:

  | Phase | Meaning |
  |-------|---------|
  | Redirects | time spent on earlier requests in the redirect chain |
  | DNS lookup | resolving the host name |
  | TCP connect | the TCP handshake |
  | TLS handshake | negotiating TLS (HTTPS only) |
  | Server response | from sending the request to the first response byte (TTFB) — the server's "thinking time" |
  | Download | receiving the body |

- **Connection:** HTTP version, whether the server offers HTTP/2 (via
  ALPN), TLS version and cipher, server IP and body size.
- **Security headers** (informational; never changes the exit code):

  | Header | Checked for |
  |--------|-------------|
  | HTTPS | served over TLS; whether `http://` redirects to `https://` |
  | Strict-Transport-Security | present with max-age ≥ 180 days |
  | Content-Security-Policy | present |
  | X-Content-Type-Options | `nosniff` |
  | X-Frame-Options | present, or CSP `frame-ancestors` |
  | Referrer-Policy, Permissions-Policy | present |
  | Server, X-Powered-By | warns when they reveal a software version |

- **Response headers.**

Reading the waterfall: a long *Server response* means the application
or database is slow. A long *TCP connect* or *TLS handshake* means
distance or network latency, where a CDN helps. A long *DNS lookup* means
a slow resolver.

| Option | Default | Description |
|--------|---------|-------------|
| `-t`, `--timeout SEC` | 8.0 | Request timeout |
| `--expect-status CODE` | — | Exit 1 unless the final status is CODE. Without it, any status ≥ 400 fails. |
| `--max-latency MS` | — | Exit 1 if the total request time is above MS |
| `--watch`, `--until-up`, `--every SEC`, `--notify`, `--webhook URL` | every: 5 | [Watch mode and alerts](#35-watch-mode-and-alerts) |
| `-4`, `-6` | — | Address family |

```bash
xping http https://example.com
xping http http://github.com                     # see the http → https redirect
xping http https://api.example.com/health --expect-status 200 --max-latency 500 -q
xping http https://example.com --watch --every 30 --notify
```

#### `xping tls`

```
xping tls HOST [--port PORT] [-t SEC] [--min-days N]
```

Inspects the certificate a server presents: protocol version, cipher,
subject, issuer, subject alternative names, validity dates, days remaining
(with a lifetime progress bar) and, on Python 3.13+, the full chain up to
the root CA. Verification is strict and uses the system store plus
`certifi`.

| Option | Default | Description |
|--------|---------|-------------|
| `--port PORT` | 443 | TCP port (e.g. 993 for IMAPS, 8443) |
| `-t`, `--timeout SEC` | 5.0 | Connection timeout |
| `--min-days N` | — | Exit 1 if the certificate expires in fewer than N days |
| `-4`, `-6` | — | Address family |

Exit code 1 when the handshake fails or the certificate has expired.
Certificates with 14 days or less left are highlighted.

```bash
xping tls github.com
xping tls mail.example.com --port 993
xping tls example.com --min-days 21 -q || echo "renew soon"
```

---

### Scanning

> Only scan networks and hosts you own or are allowed to test.

#### `xping portscan`

```
xping portscan HOST [-p LIST] [-t SEC] [-w N] [--banners]
```

Scans TCP ports concurrently and lists the open ones with their service
names. With `--banners`, it reads what each open port says first, such
as an SSH version, HTTP server, FTP/SMTP greeting, Redis, PostgreSQL,
MySQL or TLS.

| Option | Default | Description |
|--------|---------|-------------|
| `-p`, `--ports LIST` | 1-1024 | Ports and ranges, e.g. `22,80,443,8000-8100` |
| `-t`, `--timeout SEC` | 0.5 | Per-port timeout |
| `-w`, `--workers N` | 100 | Concurrent connections |
| `--banners` | — | Grab service banners from open ports |
| `-4`, `-6` | — | Address family |

```bash
xping portscan example.com --ports 22,80,443
xping portscan 192.168.1.10 -p 1-65535 -w 500 --banners
```

#### `xping sweep`

```
xping sweep RANGE [-p LIST] [-t SEC] [-w N] [--limit N]
```

Finds hosts with open TCP services across a range, for example all SSH
or web servers on a LAN. A RANGE is either a CIDR block
(`192.168.1.0/24`) or a start-end range (`10.0.0.10-10.0.0.50`).

| Option | Default | Description |
|--------|---------|-------------|
| `-p`, `--ports LIST` | 22,80,443 | Ports probed on every host |
| `-t`, `--timeout SEC` | 0.5 | Per host-port timeout |
| `-w`, `--workers N` | 128 | Concurrent hosts |
| `--limit N` | 4096 | Refuse ranges larger than N hosts |

Exit code 1 when no host has an open port.

```bash
xping sweep 192.168.1.0/24
xping sweep 10.0.0.1-10.0.0.254 --ports 3389,5900
```

#### `xping ipscan`

```
xping ipscan RANGE [-t SEC] [-w N] [--limit N]
```

Discovers live hosts in a range with ICMP echo (through the system
`ping`), and shows each responder's RTT. Hosts that block ping are not
found; use [`sweep`](#xping-sweep) for those.

| Option | Default | Description |
|--------|---------|-------------|
| `-t`, `--timeout SEC` | 1.0 | Per-IP timeout |
| `-w`, `--workers N` | 128 | Concurrent probes |
| `--limit N` | 4096 | Refuse ranges larger than N addresses |

```bash
xping ipscan 192.168.1.0/24
```

#### `xping osdetect`

```
xping osdetect HOST
```

Guesses the remote operating system from the TTL of its ping reply. Every
OS starts packets with a fixed TTL, and each router subtracts one:

| Received TTL | Likely initial TTL | Guess |
|--------------|--------------------|-------|
| ≤ 32 | 32 | old Windows |
| 33–64 | 64 | Linux, macOS, FreeBSD |
| 65–128 | 128 | Windows |
| 129–255 | 255 | network devices (Cisco IOS), Solaris, some Linux |

This is a heuristic: VPNs, NAT and load balancers can change the TTL.

| Option | Description |
|--------|-------------|
| `-4`, `-6` | Address family |

```bash
xping osdetect 192.168.1.1
```

---

### Local machine

#### `xping listen`

```
xping listen [--proto tcp|udp]
```

Lists the TCP and UDP ports your machine is listening on. It uses `ss` on
Linux and `netstat` on macOS and Windows. Process names and PIDs are
shown where the platform provides them (Linux).

| Option | Description |
|--------|-------------|
| `--proto tcp` / `--proto udp` | Show only one protocol |

```bash
xping listen
xping listen --proto tcp --json
```

#### `xping ntp`

```
xping ntp [SERVER] [-c N] [-t SEC] [--max-offset MS]
```

Measures how far this machine's clock is from an NTP server. It uses
SNTP (one small UDP packet to port 123 per sample). A wrong clock breaks
HTTPS certificate checks, logins with one-time codes (TOTP), Kerberos, log
correlation and more.

From the four timestamps of each exchange, xping computes:

- the **offset**: the server's clock minus yours. A positive offset means
  your clock is behind.
- the **round-trip delay**.

It takes several samples and reports the one with the lowest delay,
because network asymmetry is the main source of error. The **accuracy**
line shows the worst case, half the round trip. An offset smaller than
that means your clock is right; a nearer server gives a sharper number. It also shows the
server's **stratum** (1 = attached to a reference clock such as GPS, 2 =
synchronised to a stratum-1 server, …), its reference, and whether the
server itself is synchronised.

| Option | Default | Description |
|--------|---------|-------------|
| `SERVER` | pool.ntp.org | NTP server to ask (e.g. `time.apple.com`, `time.google.com`, or your own) |
| `-c`, `--count N` | 4 | Samples |
| `-t`, `--timeout SEC` | 2.0 | Seconds to wait per sample |
| `--max-offset MS` | — | Exit 1 if the clock is off by more than MS milliseconds |
| `-4`, `-6` | — | Address family |

Exit code 1 when no sample got a reply, when the server reports it is
not synchronised (stratum 16 or leap indicator 3), or when
`--max-offset` is exceeded.

```bash
xping ntp
xping ntp time.cloudflare.com --max-offset 100 -q || echo "clock drift"
```

#### `xping speedtest`

```
xping speedtest [-c N] [-d SEC]
```

Measures latency, download and upload speed against Cloudflare's speed
test service. By default it uses 4 parallel connections, because a single
stream under-reports fast links. Download is timed from the first byte;
upload is timed after the TLS handshakes. It uses up to about 40 MB down
and 8 MB up (25 MB down with `-c 1`).

Grades by download speed: Excellent ≥ 100 Mbps, Good ≥ 25, Fair ≥ 10,
Poor ≥ 1, Critical below.

| Option | Default | Description |
|--------|---------|-------------|
| `-c`, `--connections N` | 4 | Parallel connections (1 = single stream) |
| `-d`, `--duration SEC` | 8 | Maximum download measurement time |

```bash
xping speedtest
xping speedtest -c 8 --json
```

---

### Automation

#### `xping check`

```
xping check FILE [-w N]
xping check --example
```

Runs many checks from one TOML or JSON file in parallel and returns **one
exit code**, which makes the file a monitoring script. See
[Batch check files](#5-batch-check-files) for the format.

| Option | Default | Description |
|--------|---------|-------------|
| `-w`, `--workers N` | 8 | Checks run in parallel |
| `--example` | — | Print a commented example file and exit |

```bash
xping check --example > checks.toml
xping check checks.toml
xping check checks.toml --markdown > status.md
```

#### `xping diff`

```
xping diff BEFORE AFTER [--max-regression PCT]
```

Compares two `--json` results of the same check and shows what got
better or worse: "latency is 40% higher than yesterday", "the route
changed at hop 7", "DMARC went from ok to fail". Either file may be `-`
to read from stdin, so a fresh run can be piped straight in:

```bash
xping ping example.net --json > baseline.json     # once
xping ping example.net --json | xping diff baseline.json -
```

The kind of result is recognised from the JSON, and the numbers that
matter are compared, each with the direction that counts as better:

| Kind | Compared |
|------|----------|
| `ping`, `health` | average / min / max RTT, jitter, packet loss (health: score, DNS time) |
| `tcp`, `udp` | average connect / reply time, success rate |
| `http` | total time and each phase (DNS, TCP, TLS, server, download); status, final URL, HTTP version and missing security headers |
| `tls` | days remaining; issuer, expiry date, protocol |
| `trace`, `mtr` | the **route** (which hops changed), final / destination RTT and loss |
| `lookup`, `propagation` | added and removed records, per resolver |
| `dnscheck`, `doctor`, `check`, `blocklist` | score / listings, and every check, step or outcome whose status changed |
| `speedtest`, `ntp`, `wifi` | download / upload / latency, clock offset and delay, signal, SNR, link rate |
| anything else | every numeric field |

Changes under 3%, or smaller than a minimum amount (1 ms, 1 percentage
point, 2 dBm, …), count as *same*, so normal jitter is not reported as a
change.

| Option | Description |
|--------|-------------|
| `--max-regression PCT` | Exit 1 when a metric got worse by more than PCT percent, or a status got worse (e.g. a check went from pass to fail). Without it, diff only reports and exits 0. |

Comparing results of different kinds, or a file that is not xping JSON,
exits 2.

```bash
xping http https://example.com --json > before.json
xping http https://example.com --json | xping diff before.json - --max-regression 25
xping check checks.toml --json > today.json && xping diff yesterday.json today.json
```

#### `xping profile`

```
xping profile add NAME TARGET [--port PORT] [--note TEXT]
xping profile remove NAME          # alias: rm
xping profile show NAME
xping profile list [--names]
```

Saves hosts under short names in `~/.xping/profiles.json`. Any command
that takes a host accepts a profile name instead, and so do the `host`
entries in check files. Names may contain letters, digits, `.`, `_` and
`-` (up to 64 characters).

| Option | Description |
|--------|-------------|
| `--port PORT` | Store a default port with the profile (shown by `show`/`list`) |
| `--note TEXT` | A description |
| `--names` | `list` prints only the names, one per line (used by tab completion) |

```bash
xping profile add prod-db 10.0.0.5 --port 5432 --note "Production PostgreSQL"
xping ping prod-db
xping tcp prod-db 5432
xping profile list
```

---

### Utilities

#### `xping config`

```
xping config
xping config --example
```

Shows which config file is in use and every setting in it, or explains
why it is invalid. See
[Personal defaults](#37-personal-defaults-config-file).

| Option | Description |
|--------|-------------|
| `--example` | Print a commented example config and exit |

```bash
xping config --example > ~/.xping/config.toml
xping config
```

#### `xping completion`

```
xping completion [bash|zsh|fish]
xping completion [SHELL] --install
xping completion [SHELL] --uninstall
```

Tab completion covers:

- commands and profile sub-commands;
- every option, with descriptions in zsh and fish;
- option values with fixed choices (`--proto`, `--type`);
- host names and saved profiles wherever a host is expected;
- `.toml` / `.json` files for `check`.

`--install` detects your shell from `$SHELL` and writes the script. It
adds a marked block to `~/.zshrc` (zsh), `~/.bashrc` (bash on Linux) or
`~/.bash_profile` (bash on macOS). For fish it writes
`~/.config/fish/completions/xping.fish`. Running it again is safe;
re-run after upgrading. `--uninstall` removes exactly what `--install`
added.

| Option | Description |
|--------|-------------|
| `SHELL` | `bash`, `zsh` or `fish`. Without `--install`/`--uninstall`, prints the script. |
| `--install` | Set completion up for the shell (default: your login shell) |
| `--uninstall` | Remove it |

Manual setup instead of `--install`:

```bash
source <(xping completion zsh)                                # in ~/.zshrc
eval "$(xping completion bash)"                               # in ~/.bashrc or ~/.bash_profile
xping completion fish > ~/.config/fish/completions/xping.fish
```

On macOS, use `eval` for bash: the system bash 3.2 ignores `source <(…)`.

#### `xping deps`

```
xping deps
```

Shows which optional system tools are available: `ping`, `traceroute`,
`dig`, `ss`/`netstat`. For missing tools it prints the right install
command for your Linux distribution or macOS. It also shows whether
native ICMP sockets work.

#### `xping about`

```
xping about
```

Prints the version, author, license, source URL and attribution notice.

---

## 5. Batch check files

A check file lists checks. Each check has a `type`, the keys that type
requires, optional settings and optional thresholds. Values in
`[defaults]` apply to every check unless the check overrides them.

**TOML** (needs Python 3.11+):

```toml
[defaults]
timeout = 3

[[check]]
name = "Database port"
type = "tcp"
host = "prod-db"            # saved profile names work
port = 5432
max_latency = 50

[[check]]
name = "Website"
type = "http"
url = "https://example.com"
expect_status = 200
max_latency = 1500
```

**JSON** (any Python version) uses the same keys:

```json
{
  "defaults": {"timeout": 3},
  "checks": [
    {"name": "Database port", "type": "tcp", "host": "prod-db", "port": 5432},
    {"name": "Website", "type": "http", "url": "https://example.com", "expect_status": 200}
  ]
}
```

**Check types and keys:**

| Type | Required | Optional | Thresholds |
|------|----------|----------|------------|
| `ping` | `host` | `count` (4), `timeout` (2.0), `interval` (0.2), `family` | `max_loss`, `max_latency` |
| `tcp` | `host`, `port` | `count` (1), `timeout` (2.0), `interval` (0.2), `family` | `max_latency` |
| `udp` | `host`, `port` | `count` (1), `timeout` (2.0), `interval` (0.2), `probe` ("auto"), `payload` (hex), `family` | `max_latency` |
| `ntp` | — | `server` ("pool.ntp.org"), `count` (2), `timeout` (2.0), `family` | `max_offset` |
| `http` | `url` | `timeout` (8.0), `family` | `expect_status`, `max_latency` |
| `tls` | `host` | `port` (443), `timeout` (5.0), `family` | `min_days` |
| `lookup` | `host` | `full` (false), `server` | — |
| `dnscheck` | `domain` | — | `min_score` |
| `blocklist` | `target` | `zones` (list), `timeout` (5.0) | — (fails when listed) |
| `health` | `host` | `count` (8), `timeout` (2.0), `family` | `min_score` |
| `propagation` | `name_to_query` | `record` ("A"), `servers` (list) | `expect` (string or list) |

Additional rules:

- `name` is optional. It defaults to `"<type> <target>"`.
- `family` is `4` / `"ipv4"` or `6` / `"ipv6"`.
- Files may be UTF-8 (with or without BOM) or UTF-16 with a BOM, which
  is what Windows PowerShell writes for `xping check --example > checks.toml`.
- An invalid file (unknown type, missing key, bad syntax) exits 2 with a
  message that names the problem.

Output is a table of all checks with pass/fail, details and timing. It
exits 0 only when every check passed. `--json` includes each check's full
underlying result.

---

## 6. Recipes

**"The internet is down" — start here**

```bash
xping doctor
```

**A website is slow: where is the time spent?**

```bash
xping http https://example.com      # waterfall: DNS, connect, TLS, server, download
xping mtr example.com --cycles 30   # is there loss or latency on the path?
```

**A service is unreachable: is it the network, the firewall or the service?**

```bash
xping doctor db.example.com --port 5432   # basics first, then the host
xping trace db.example.com --tcp --port 5432
xping tcp db.example.com 5432
```

**Wait for a server to come back, then continue**

```bash
xping tcp app.internal 22 --until-up -q --notify && ssh app.internal
```

**Watch a website and alert a Slack channel**

```bash
xping http https://example.com --watch --every 60 \
      --webhook https://hooks.slack.com/services/T000/B000/XXXX
```

**Is this machine's clock right?**

```bash
xping ntp --max-offset 500
```

**Is the DNS server (UDP) answering?**

```bash
xping udp 192.168.1.1 53
```

**Certificate expiry alarm (cron)**

```cron
0 8 * * *  xping tls example.com --min-days 21 -q || mail -s "TLS cert expiring" ops@example.com < /dev/null
```

**Health checks in CI**

```yaml
- run: pipx install xping
- run: xping check deploy-checks.json    # JSON works on every Python version
```

**Did my DNS change propagate?**

```bash
xping propagation www.example.com --expect 203.0.113.10
```

**Audit a mail domain / "why does my mail bounce?"**

```bash
xping dnscheck example.com        # SPF, DMARC, DKIM, MX
xping blocklist example.com       # the domain and its mail servers on spam blocklists
xping lookup example.com --full
```

**Find devices on the LAN**

```bash
xping net                          # your subnet and gateway
xping ipscan 192.168.1.0/24        # hosts that answer ping
xping sweep 192.168.1.0/24 -p 22,80,443,3389
```

**Did it get worse since last time?**

```bash
xping mtr example.net --json > mtr-monday.json
# later
xping mtr example.net --json | xping diff mtr-monday.json -   # route and loss changes
```

**Save a report**

```bash
xping all example.com --markdown > report.md
xping doctor --json > doctor.json
```

---

## 7. Files, environment and privacy

**Files.** Everything xping writes is stored under `~/.xping/`:

| Path | Contents |
|------|----------|
| `~/.xping/profiles.json` | Saved profiles |
| `~/.xping/health_history.json` | `health` score history (last 50 per host) |
| `~/.xping/completions/` | Completion scripts written by `completion --install` |
| `~/.xping/config.toml` | Your defaults (you write it; xping only reads it) |

`completion --install` also adds a marked block to your shell's rc file
(or a file under `~/.config/fish/completions/`).

**Environment variables.**

| Variable | Effect |
|----------|--------|
| `NO_COLOR` | Disable colour output |
| `XPING_DEBUG` | Print full Python tracebacks on errors |
| `XPING_CONFIG` | Use another config file; `none` ignores the config |
| `SHELL` | The shell `completion --install` sets up |
| `ZDOTDIR`, `XDG_CONFIG_HOME` | Honoured by `completion --install` for the zsh rc and fish config locations |

**Privacy.** Diagnostics contact the host you name. These features also
contact third parties, and only when you use them:

| Feature | Contacts |
|---------|----------|
| `doctor` | 1.1.1.1, 8.8.8.8, 9.9.9.9 (TCP 443, ping, one DNS query); `captive.apple.com` (HTTP); `www.cloudflare.com` (HTTPS) |
| `net` | `1.1.1.1` for your public IP — skip with `--no-public` |
| `ntp` | `pool.ntp.org` unless you name another server |
| `speedtest` | `speed.cloudflare.com` |
| `trace --asn`, `mtr --asn` | Team Cymru DNS (hop addresses are looked up there) |
| `propagation` | Google, Cloudflare, Quad9, OpenDNS, AdGuard and Control D resolvers |
| `whois` | IANA and registry WHOIS / RDAP servers |
| `blocklist` | the blocklists' DNS servers (via your resolver), which see the checked IP or domain |
| `lookup`, `dnscheck` | `8.8.8.8`, only when `dig` is not installed |
| `lookup --doh` | the DoH provider you choose (Cloudflare, Google, Quad9 or your URL) |
| `dnscheck` | `1.1.1.1` (or `8.8.8.8`) for the DNSSEC check |
| `rdns` | `8.8.8.8`, only when the system resolver has no PTR record |
| `--webhook URL` | only the URL you give |

xping has no telemetry and makes no update checks. TLS verification is
always on and cannot be disabled. External tools are run with argument
lists, never through a shell.

---

## 8. Platform notes

**Linux.**

- Everything works.
- ICMP needs no root when ping sockets are allowed, which is the default
  on current distributions.
- `listen` shows process names.
- The PPA package includes the man page and completion for all three
  shells.

**macOS.**

- Everything works without root.
- `mtu -6` needs root for the IPv6 don't-fragment probe.
- `listen` shows ports, but no process names.
- `--notify` alerts appear in Notification Center.

**Windows.**

- These work natively: TCP, `portscan`, `sweep`, `http`, `tls`, DNS,
  `net`, `check`, `doctor`, `speedtest`.
- `ping` and `trace` use the built-in `ping` / `tracert`.
- Not available: `trace --tcp`, and `mtu -6`.
- `--notify` falls back to the terminal bell.
- Tab completion works in bash, zsh or fish (WSL, Git Bash); PowerShell
  completion is not provided yet.

---

## 9. Troubleshooting and FAQ

**Every hop in `trace` shows `* * *` after a certain point.**
A firewall is dropping the probes. Try `xping trace HOST --tcp` (or
`--port` with the service's port). TCP probes usually get through.

**`ping` says unreachable, but the website works in my browser.**
Many servers and cloud providers block ICMP. Use `xping tcp HOST 443`,
`xping http URL` or `xping doctor HOST` instead.

**`doctor` says "The router works, but there is no internet behind it".**
Restart the modem and router. If that does not help, contact your ISP.
You can check again from a phone hotspot to confirm that the problem is
your line.

**`doctor` warns that the system clock is off.**
Turn on automatic date and time. A wrong clock breaks HTTPS certificate
checks and logins.

**Tab completion does not work.**
Run `xping completion --install` again and open a new terminal. On macOS
with bash, make sure your terminal reads `~/.bash_profile`. In zsh, a
plugin framework that runs `compinit` after the xping block is fine; the
block registers itself explicitly.

**`xping check` says TOML needs Python 3.11+.**
Use a `.json` check file, which has the same keys, or upgrade Python.

**Colours look wrong, or I want plain text.**
Set `NO_COLOR=1`, or use `--markdown` / `--csv`.

**Where do I report a bug?**
At <https://github.com/mehaskari/xping/issues>. The bug report form asks
for the xping version, OS, install method and the exact command. Report
security issues privately as described in
[SECURITY.md](../SECURITY.md).
