"""Argument parser construction for the xping CLI."""

from __future__ import annotations

import argparse

from xping.diagnostics.portscan import parse_ports


def _tcp_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _port_list(value: str) -> list[int]:
    try:
        return parse_ports(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_ports_default(value: str) -> list[int]:
    return parse_ports(value)


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def _non_negative_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a number") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("value must not be negative")
    return number


def _score(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("score must be an integer") from exc
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("score must be between 0 and 100")
    return number


def _hex_payload(value: str) -> str:
    cleaned = value.replace(" ", "").replace(":", "")
    try:
        bytes.fromhex(cleaned)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "payload must be hex bytes, e.g. 0d0a or 'de ad be ef'"
        ) from exc
    return cleaned


def _export_parent() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    out = parent.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    out.add_argument("--csv", action="store_true", help="Emit CSV output")
    out.add_argument("--markdown", action="store_true", help="Emit Markdown output")
    out.add_argument(
        "-q", "--quiet", action="store_true", help="No output — report only via the exit code"
    )
    return parent


def _add_family(p: argparse.ArgumentParser) -> None:
    fam = p.add_mutually_exclusive_group()
    fam.add_argument("-4", "--ipv4", action="store_true", help="Use IPv4 only")
    fam.add_argument("-6", "--ipv6", action="store_true", help="Use IPv6 only")


def _positive_float(value: str) -> float:
    number = _non_negative_float(value)
    if number == 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def _webhook_url(value: str) -> str:
    from xping.diagnostics.notify import valid_webhook

    if not valid_webhook(value):
        raise argparse.ArgumentTypeError("webhook must be an http:// or https:// URL")
    return value


def _add_notify(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--notify",
        action="store_true",
        help="Desktop notification when the target goes down or comes back (watch mode)",
    )
    p.add_argument(
        "--webhook",
        type=_webhook_url,
        default=None,
        metavar="URL",
        help="POST a JSON event to URL on every down/up change (Slack, Discord, …)",
    )


def _add_watch(p: argparse.ArgumentParser, every: float) -> None:
    p.add_argument(
        "--watch",
        action="store_true",
        help="Repeat the check until Ctrl-C, highlighting up/down changes",
    )
    p.add_argument(
        "--until-up",
        action="store_true",
        help="Repeat the check until it passes, then exit 0 (works with --quiet)",
    )
    p.add_argument(
        "--every",
        type=_positive_float,
        default=every,
        metavar="SEC",
        help=f"Seconds between checks in watch mode [default: {every:g}]",
    )
    _add_notify(p)


def _add_max_loss(p: argparse.ArgumentParser, what: str = "packet loss") -> None:
    p.add_argument(
        "--max-loss",
        type=_non_negative_float,
        default=None,
        metavar="PCT",
        help=f"Exit 1 if {what} exceeds PCT percent",
    )


def _add_max_latency(p: argparse.ArgumentParser, what: str = "average latency") -> None:
    p.add_argument(
        "--max-latency",
        type=_non_negative_float,
        default=None,
        metavar="MS",
        help=f"Exit 1 if {what} exceeds MS milliseconds",
    )


def _add_min_score(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--min-score",
        type=_score,
        default=None,
        metavar="N",
        help="Exit 1 if the score (0-100) is below N",
    )


def build_parser() -> argparse.ArgumentParser:
    export_parent = _export_parent()
    parser = argparse.ArgumentParser(
        prog="xping",
        description="Beautiful CLI network diagnostics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  ping   <host>        ICMP echo — latency and packet loss  (--watch for live mode)
  trace  <host>        Hop-by-hop traceroute  (--tcp through firewalls that drop ping)
  lookup <host>        DNS A, AAAA, MX, NS, TXT records
  tcp    <host> <port> TCP port connectivity and timing
  udp    <host> <port> UDP service probe (DNS, NTP, SNMP, or raw payload)
  ntp    [server]      System clock offset against an NTP server
  portscan <host>      TCP port scanner
  sweep  <range>       TCP sweep across CIDR / start-end IP range
  ipscan <range>       Discover live IPs with ICMP echo probes
  all    <host>        Run lookup, ping, trace, and TCP checks
  check  <file>        Run many checks from a TOML/JSON file — one exit code
  rdns   <ip>          Reverse DNS (PTR) lookup
  tls    <host>        TLS/SSL certificate inspector
  http   <url>         HTTP status, headers, redirects, and TTFB
  whois  <domain>      WHOIS registration lookup
  health <host>        Network health score (DNS + loss + latency + jitter)
  mtr    <host>        Combined traceroute + live per-hop ping
  mtu    <host>        Path MTU discovery (binary search)
  dnscheck <domain>    DNS health check — SPF, DMARC, DKIM, NS, MX
  blocklist <ip|domain> Spam blocklist (DNSBL) check — IP, or a domain's mail servers
  propagation <name>   Compare answers from public resolvers (DNS propagation)
  osdetect <host>      Guess remote OS from TTL fingerprint
  speedtest            Download/upload speed via Cloudflare
  listen               Show locally listening TCP/UDP ports
  net                  Local network overview: interfaces, gateway, DNS, public IP
  doctor [host]        Why is the internet not working? Step-by-step diagnosis
  deps                 Check system dependency status
  completion [shell]   Tab completion for bash/zsh/fish (--install to set it up)
  about                Show author, license, and attribution info
  profile              Manage saved target profiles
    add <name> <target>   Save a profile
    remove <name>         Delete a profile
    list                  List all profiles
    show <name>           Show one profile

Examples:
  xping ping google.com
  xping ping google.com --watch
  xping tcp db.local 5432 --watch --notify
  xping http https://example.com --watch --webhook https://hooks.slack.com/services/…
  xping trace 1.1.1.1 --max-hops 20
  xping trace example.com --tcp --port 443
  xping lookup github.com --full --markdown
  xping tcp example.com 443 -c 5
  xping udp 1.1.1.1 53
  xping ntp --max-offset 500
  xping portscan example.com --ports 22,80,443
  xping sweep 192.168.1.0/24 --ports 22,80,443
  xping ipscan 192.168.1.0/24
  xping rdns 8.8.8.8
  xping tls github.com
  xping http https://example.com
  xping whois cloudflare.com
  xping health google.com
  xping mtr 1.1.1.1 --cycles 15
  xping mtu 8.8.8.8
  xping dnscheck github.com
  xping blocklist mail.example.net
  xping propagation example.com --type MX
  xping propagation example.com --expect 93.184.216.34
  xping speedtest --json
  xping net
  xping doctor
  xping doctor github.com --port 22
  xping profile add prod-db 10.0.0.5 --port 5432 --note "Production DB"
  xping profile list
  xping ping prod-db
  xping all cloudflare.com
  xping check --example > checks.toml && xping check checks.toml

Exit codes: 0 check passed · 1 check failed · 2 invalid usage · 130 interrupted
Thresholds (e.g. --max-loss, --max-latency, --min-days) turn checks into alarms;
add -q for exit-code-only output. IPv6: -6 (or -4 to force IPv4).
        """,
    )

    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Show version and exit",
    )

    sub = parser.add_subparsers(dest="command")

    p_ping = sub.add_parser("ping", parents=[export_parent], help="ICMP ping a host")
    p_ping.add_argument("host", help="Hostname or IP address")
    p_ping.add_argument(
        "-c", "--count", type=int, default=5, metavar="N", help="Number of packets [default: 5]"
    )
    _add_family(p_ping)
    p_ping.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Per-packet timeout [default: 2.0]",
    )
    p_ping.add_argument(
        "-i",
        "--interval",
        type=float,
        default=0.5,
        metavar="SEC",
        help="Interval between pings [default: 0.5]",
    )
    p_ping.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Continuous live ping with sparkline (Ctrl-C to stop)",
    )
    _add_notify(p_ping)
    _add_max_loss(p_ping)
    _add_max_latency(p_ping, "average RTT")

    p_trace = sub.add_parser("trace", parents=[export_parent], help="Traceroute to a host")
    p_trace.add_argument("host", help="Hostname or IP address")
    p_trace.add_argument(
        "-m", "--max-hops", type=int, default=30, metavar="N", help="Maximum hops [default: 30]"
    )
    _add_family(p_trace)
    p_trace.add_argument(
        "--asn",
        action="store_true",
        help="Show the network operator (AS number/name) of each hop via Team Cymru DNS",
    )
    p_trace.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Per-hop timeout [default: 2.0]",
    )
    p_trace.add_argument(
        "-p", "--probes", type=int, default=3, metavar="N", help="Probes per hop [default: 3]"
    )
    p_trace.add_argument(
        "-T",
        "--tcp",
        action="store_true",
        help="Probe with TCP SYNs instead of ICMP — gets through firewalls that drop ping",
    )
    p_trace.add_argument(
        "--port",
        type=_tcp_port,
        default=None,
        metavar="PORT",
        help="TCP port for --tcp (implies --tcp) [default: 443]",
    )

    p_lookup = sub.add_parser("lookup", parents=[export_parent], help="DNS lookup for a host")
    p_lookup.add_argument("host", help="Hostname or IP address")
    p_lookup.add_argument(
        "--full", "-f", action="store_true", help="Include TXT records (SPF, DMARC, DKIM…)"
    )
    p_lookup.add_argument(
        "--server",
        "-s",
        default=None,
        metavar="IP",
        help="Custom DNS server, e.g. 8.8.8.8 or 1.1.1.1 (like dig @server)",
    )

    p_tcp = sub.add_parser("tcp", parents=[export_parent], help="Test TCP connectivity")
    p_tcp.add_argument("host", help="Hostname or IP address")
    p_tcp.add_argument("port", type=_tcp_port, help="TCP port number")
    p_tcp.add_argument(
        "-c",
        "--count",
        type=int,
        default=3,
        metavar="N",
        help="Number of connection attempts [default: 3]",
    )
    _add_family(p_tcp)
    _add_watch(p_tcp, 2.0)
    p_tcp.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Per-attempt timeout [default: 2.0]",
    )
    p_tcp.add_argument(
        "-i",
        "--interval",
        type=float,
        default=0.5,
        metavar="SEC",
        help="Interval between attempts [default: 0.5]",
    )
    _add_max_latency(p_tcp, "average connect time")

    p_udp = sub.add_parser(
        "udp", parents=[export_parent], help="Probe a UDP service (DNS, NTP, SNMP, raw)"
    )
    p_udp.add_argument("host", help="Hostname or IP address")
    p_udp.add_argument("port", type=_tcp_port, help="UDP port number")
    p_udp.add_argument(
        "-c",
        "--count",
        type=_positive_int,
        default=3,
        metavar="N",
        help="Probes to send [default: 3]",
    )
    p_udp.add_argument(
        "--probe",
        choices=["auto", "dns", "ntp", "snmp", "empty"],
        default="auto",
        help="Request to send [default: auto — by port: 53 dns, 123 ntp, 161 snmp]",
    )
    p_udp.add_argument(
        "--payload", type=_hex_payload, default=None, metavar="HEX", help="Send these bytes instead"
    )
    _add_family(p_udp)
    _add_watch(p_udp, 5.0)
    p_udp.add_argument(
        "-t",
        "--timeout",
        type=_positive_float,
        default=2.0,
        metavar="SEC",
        help="Seconds to wait for a reply [default: 2.0]",
    )
    p_udp.add_argument(
        "-i",
        "--interval",
        type=_non_negative_float,
        default=0.5,
        metavar="SEC",
        help="Interval between probes [default: 0.5]",
    )
    _add_max_latency(p_udp, "average reply time")

    p_ntp = sub.add_parser(
        "ntp", parents=[export_parent], help="Check the system clock against an NTP server"
    )
    p_ntp.add_argument(
        "server", nargs="?", default="pool.ntp.org", help="NTP server [default: pool.ntp.org]"
    )
    p_ntp.add_argument(
        "-c", "--count", type=_positive_int, default=4, metavar="N", help="Samples [default: 4]"
    )
    _add_family(p_ntp)
    p_ntp.add_argument(
        "-t",
        "--timeout",
        type=_positive_float,
        default=2.0,
        metavar="SEC",
        help="Seconds to wait per sample [default: 2.0]",
    )
    p_ntp.add_argument(
        "--max-offset",
        type=_non_negative_float,
        default=None,
        metavar="MS",
        help="Exit 1 if the clock is off by more than MS milliseconds",
    )

    p_portscan = sub.add_parser("portscan", parents=[export_parent], help="Scan TCP ports")
    p_portscan.add_argument("host", help="Hostname or IP address")
    p_portscan.add_argument(
        "--ports",
        "-p",
        type=_port_list,
        default=parse_ports_default("1-1024"),
        metavar="LIST",
        help="Ports/ranges [default: 1-1024]",
    )
    _add_family(p_portscan)
    p_portscan.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=0.5,
        metavar="SEC",
        help="Per-port timeout [default: 0.5]",
    )
    p_portscan.add_argument(
        "-w",
        "--workers",
        type=_positive_int,
        default=100,
        metavar="N",
        help="Concurrent workers [default: 100]",
    )
    p_portscan.add_argument(
        "--banners", action="store_true", help="Grab service banners from open ports"
    )

    p_sweep = sub.add_parser(
        "sweep", parents=[export_parent], help="Scan an IP range for open ports"
    )
    p_sweep.add_argument("target", help="CIDR or start-end IP range")
    p_sweep.add_argument(
        "--ports",
        "-p",
        type=_port_list,
        default=parse_ports_default("22,80,443"),
        metavar="LIST",
        help="Probe ports [default: 22,80,443]",
    )
    p_sweep.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=0.5,
        metavar="SEC",
        help="Per host-port timeout [default: 0.5]",
    )
    p_sweep.add_argument(
        "-w",
        "--workers",
        type=_positive_int,
        default=128,
        metavar="N",
        help="Concurrent host workers [default: 128]",
    )
    p_sweep.add_argument(
        "--limit",
        type=_positive_int,
        default=4096,
        metavar="N",
        help="Maximum hosts to scan [default: 4096]",
    )

    p_ipscan = sub.add_parser("ipscan", parents=[export_parent], help="Discover live IPs")
    p_ipscan.add_argument("target", help="CIDR or start-end IP range")
    p_ipscan.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=1.0,
        metavar="SEC",
        help="Per-IP ping timeout [default: 1.0]",
    )
    p_ipscan.add_argument(
        "-w",
        "--workers",
        type=_positive_int,
        default=128,
        metavar="N",
        help="Concurrent IP workers [default: 128]",
    )
    p_ipscan.add_argument(
        "--limit",
        type=_positive_int,
        default=4096,
        metavar="N",
        help="Maximum IPs to scan [default: 4096]",
    )

    p_all = sub.add_parser(
        "all", parents=[export_parent], help="Run lookup, ping, trace, and TCP checks"
    )
    _add_family(p_all)
    p_all.add_argument("host", help="Hostname or IP address")

    p_check = sub.add_parser(
        "check",
        parents=[export_parent],
        help="Run many checks from a TOML/JSON file (one exit code)",
    )
    p_check.add_argument("file", nargs="?", help="Check file (.toml or .json)")
    p_check.add_argument(
        "-w",
        "--workers",
        type=_positive_int,
        default=8,
        metavar="N",
        help="Checks to run in parallel [default: 8]",
    )
    p_check.add_argument(
        "--example", action="store_true", help="Print an example check file and exit"
    )

    p_rdns = sub.add_parser("rdns", parents=[export_parent], help="Reverse DNS (PTR) lookup")
    p_rdns.add_argument("ip", help="IP address to resolve")

    p_dnscheck = sub.add_parser(
        "dnscheck", parents=[export_parent], help="DNS health check — SPF, DMARC, DKIM, MX, NS"
    )
    p_dnscheck.add_argument("domain", help="Domain name to check")
    _add_min_score(p_dnscheck)

    p_block = sub.add_parser(
        "blocklist",
        parents=[export_parent],
        help="Check an IP or a domain's mail servers against spam blocklists (DNSBL)",
    )
    p_block.add_argument("target", help="IPv4 address or domain")
    p_block.add_argument(
        "--zone",
        action="append",
        default=None,
        metavar="ZONE",
        help="Also check this DNSBL zone, e.g. bl.example.org (repeatable)",
    )
    p_block.add_argument(
        "-t",
        "--timeout",
        type=_positive_float,
        default=5.0,
        metavar="SEC",
        help="Seconds to wait per lookup [default: 5]",
    )

    p_prop = sub.add_parser(
        "propagation",
        parents=[export_parent],
        help="Compare a record across public resolvers (DNS propagation)",
    )
    p_prop.add_argument("name", help="DNS name to query")
    p_prop.add_argument(
        "--type",
        "-t",
        dest="rtype",
        default="A",
        type=str.upper,
        choices=["A", "AAAA", "CNAME", "MX", "NS", "TXT"],
        help="Record type [default: A]",
    )
    p_prop.add_argument(
        "--expect",
        action="append",
        default=None,
        metavar="VALUE",
        help="Exit 1 unless every resolver returns VALUE (repeatable; MX as 'PRIO HOST')",
    )
    p_prop.add_argument(
        "--server",
        "-s",
        action="append",
        default=None,
        metavar="IP",
        help="Also query this resolver (repeatable)",
    )
    p_prop.add_argument("--no-system", action="store_true", help="Skip your own system resolver")

    p_tls = sub.add_parser("tls", parents=[export_parent], help="TLS/SSL certificate inspector")
    p_tls.add_argument("host", help="Hostname to connect to")
    p_tls.add_argument(
        "--port", type=_tcp_port, default=443, metavar="PORT", help="TCP port [default: 443]"
    )
    _add_family(p_tls)
    p_tls.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=5.0,
        metavar="SEC",
        help="Connection timeout [default: 5.0]",
    )
    p_tls.add_argument(
        "--min-days",
        type=int,
        default=None,
        metavar="N",
        help="Exit 1 if the certificate expires in fewer than N days",
    )

    p_http = sub.add_parser(
        "http", parents=[export_parent], help="HTTP diagnostics (status, headers, TTFB)"
    )
    _add_family(p_http)
    _add_watch(p_http, 5.0)
    p_http.add_argument("url", help="URL to request (http:// or https://)")
    p_http.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=8.0,
        metavar="SEC",
        help="Request timeout [default: 8.0]",
    )
    _add_max_latency(p_http, "total request time")
    p_http.add_argument(
        "--expect-status",
        type=int,
        default=None,
        metavar="CODE",
        help="Exit 1 unless the final HTTP status is CODE (default: fail on >= 400)",
    )

    p_whois = sub.add_parser("whois", parents=[export_parent], help="WHOIS domain lookup")
    p_whois.add_argument("domain", help="Domain name to look up")

    p_health = sub.add_parser("health", parents=[export_parent], help="Network health score")
    p_health.add_argument("host", help="Hostname or IP address")
    p_health.add_argument(
        "-c",
        "--count",
        type=int,
        default=8,
        metavar="N",
        help="Ping packets for scoring [default: 8]",
    )
    _add_family(p_health)
    _add_watch(p_health, 30.0)
    p_health.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Per-packet timeout [default: 2.0]",
    )
    _add_min_score(p_health)

    p_mtr = sub.add_parser(
        "mtr", parents=[export_parent], help="Combined traceroute + live per-hop ping"
    )
    _add_family(p_mtr)
    p_mtr.add_argument(
        "--asn",
        action="store_true",
        help="Show the network operator (AS number/name) of each hop via Team Cymru DNS",
    )
    p_mtr.add_argument("host", help="Hostname or IP address")
    p_mtr.add_argument(
        "-c",
        "--cycles",
        type=int,
        default=10,
        metavar="N",
        help="Ping cycles per hop [default: 10]",
    )
    p_mtr.add_argument(
        "-m", "--max-hops", type=int, default=30, metavar="N", help="Maximum hops [default: 30]"
    )
    p_mtr.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Per-probe timeout [default: 2.0]",
    )
    p_mtr.add_argument(
        "-i",
        "--interval",
        type=float,
        default=0.3,
        metavar="SEC",
        help="Interval between cycles [default: 0.3]",
    )
    _add_max_loss(p_mtr, "destination packet loss")
    _add_max_latency(p_mtr, "destination average RTT")

    p_mtu = sub.add_parser("mtu", parents=[export_parent], help="Path MTU discovery")
    p_mtu.add_argument("host", help="Hostname or IP address")
    p_mtu.add_argument(
        "--max-mtu", type=int, default=1500, metavar="BYTES", help="Search ceiling [default: 1500]"
    )
    _add_family(p_mtu)
    p_mtu.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Per-probe timeout [default: 2.0]",
    )

    p_profile = sub.add_parser("profile", help="Manage saved target profiles")
    profile_sub = p_profile.add_subparsers(dest="profile_action")

    p_prof_add = profile_sub.add_parser("add", help="Save a profile")
    p_prof_add.add_argument("name", help="Short profile name")
    p_prof_add.add_argument("target", help="Hostname or IP address")
    p_prof_add.add_argument(
        "--port", type=_tcp_port, default=None, metavar="PORT", help="Optional default port"
    )
    p_prof_add.add_argument("--note", default=None, help="Optional description")

    p_prof_rm = profile_sub.add_parser("remove", aliases=["rm"], help="Delete a profile")
    p_prof_rm.add_argument("name", help="Profile name to remove")

    p_prof_show = profile_sub.add_parser("show", help="Show a single profile")
    p_prof_show.add_argument("name", help="Profile name")

    p_prof_list = profile_sub.add_parser("list", help="List all saved profiles")
    p_prof_list.add_argument(
        "--names", action="store_true", help="Print only profile names, one per line"
    )

    p_speed = sub.add_parser(
        "speedtest",
        parents=[export_parent],
        help="Measure download/upload speed via Cloudflare",
    )
    p_speed.add_argument(
        "-c",
        "--connections",
        type=_positive_int,
        default=4,
        metavar="N",
        help="Parallel connections [default: 4; 1 = single-stream]",
    )
    p_speed.add_argument(
        "-d",
        "--duration",
        type=_positive_float,
        default=8.0,
        metavar="SEC",
        help="Maximum download measurement time [default: 8]",
    )

    p_completion = sub.add_parser(
        "completion", help="Tab completion: print a script or --install it for your shell"
    )
    p_completion.add_argument(
        "shell",
        nargs="?",
        choices=["bash", "zsh", "fish"],
        help="Shell [default with --install/--uninstall: your login shell]",
    )
    comp_action = p_completion.add_mutually_exclusive_group()
    comp_action.add_argument(
        "--install",
        action="store_true",
        help="Install completion for the shell (writes the script, updates your shell rc file)",
    )
    comp_action.add_argument("--uninstall", action="store_true", help="Remove what --install added")

    p_listen = sub.add_parser(
        "listen", parents=[export_parent], help="Show locally listening TCP/UDP ports"
    )
    p_listen.add_argument(
        "--proto", choices=["tcp", "udp"], default=None, help="Filter by protocol (default: both)"
    )

    p_osdetect = sub.add_parser(
        "osdetect", parents=[export_parent], help="Guess remote OS from TTL fingerprint"
    )
    _add_family(p_osdetect)
    p_osdetect.add_argument("host", help="Hostname or IP address")

    p_net = sub.add_parser(
        "net",
        parents=[export_parent],
        help="Local network overview: interfaces, gateway, DNS, public IP",
    )
    p_net.add_argument(
        "--no-public",
        action="store_true",
        help="Skip the public IP lookup (no traffic leaves your network)",
    )
    p_net.add_argument(
        "--all", action="store_true", help="Also list interfaces with only link-local addresses"
    )

    p_doctor = sub.add_parser(
        "doctor",
        parents=[export_parent],
        help="Diagnose why the internet (or a host) is not working",
    )
    p_doctor.add_argument(
        "host", nargs="?", default=None, help="Optional host to test after the basics"
    )
    p_doctor.add_argument(
        "--port",
        type=_tcp_port,
        default=443,
        metavar="PORT",
        help="TCP port to test on HOST [default: 443]",
    )

    sub.add_parser("deps", help="Check system dependency status")
    sub.add_parser("about", help="Show author, license, and attribution info")

    return parser
