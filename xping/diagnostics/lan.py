"""
xping.diagnostics.lan — which devices are on this network?

``xping lan [CIDR]`` nudges every address of the local subnet with one
empty UDP datagram (to the discard port), which makes the system resolve
each address with ARP. No root and no ICMP needed: whatever answered is in
the neighbour table afterwards, which is read back (``/proc/net/arp`` on
Linux, ``arp -an`` on macOS, ``arp -a`` on Windows). Each device then gets
a name, asked from the device itself over mDNS (port 5353, as Apple, most
printers and many smart devices answer) and from the router's DNS, and a
vendor from its MAC prefix when a vendor database is installed (nmap,
Wireshark or the IEEE list from ieee-data / hwdata). Nothing leaves the
local network.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from xping.diagnostics import net as net_diag
from xping.diagnostics import rdns as rdns_diag
from xping.models.lan import LanDevice, LanResult
from xping.render import BRAND_TEAL, c, section_header
from xping.render.animations import Spinner
from xping.render.views import lan as lan_view

MAX_HOSTS = 4096  # a /20; larger networks need an explicit, smaller CIDR
DEFAULT_MAX_PREFIX = 22  # without a CIDR, scan at most a /22 of a larger subnet
_DISCARD_PORT = 9
_SETTLE = 1.5  # seconds for ARP replies to arrive after the probes
_NAME_TIMEOUT = 1.0
_MAC_RE = re.compile(r"^([0-9a-f]{1,2}[:-]){5}[0-9a-f]{1,2}$", re.I)

_VENDOR_DBS = (
    "/usr/share/nmap/nmap-mac-prefixes",
    "/usr/local/share/nmap/nmap-mac-prefixes",
    "/opt/homebrew/share/nmap/nmap-mac-prefixes",
    "/usr/share/wireshark/manuf",
    "/Applications/Wireshark.app/Contents/Resources/share/wireshark/manuf",
    "/usr/share/ieee-data/oui.txt",
    "/usr/share/hwdata/oui.txt",
    "/usr/share/misc/oui.txt",
    r"C:\Program Files\Nmap\nmap-mac-prefixes",
    r"C:\Program Files\Wireshark\manuf",
)


# ── MAC addresses and vendors ────────────────────────────────────────────────


def normalize_mac(mac: str) -> str | None:
    """'e0:a4:98:5:e:68' / 'E0-A4-98-05-0E-68' → 'e0:a4:98:05:0e:68'."""
    mac = mac.strip()
    if not _MAC_RE.match(mac):
        return None
    return ":".join(part.zfill(2) for part in re.split("[:-]", mac.lower()))


def is_random_mac(mac: str) -> bool:
    """Locally administered: phones and laptops use these for privacy."""
    return bool(int(mac[:2], 16) & 0x02)


def _unusable(mac: str) -> bool:
    first = int(mac[:2], 16)
    return mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff") or bool(first & 0x01)


def parse_vendor_db(text: str) -> dict[str, str]:
    """{'b827eb': 'Raspberry Pi Foundation'} from nmap-mac-prefixes, a
    Wireshark manuf file or the IEEE oui.txt (24-bit prefixes only)."""
    vendors: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "(base 16)" in line:
            continue  # oui.txt repeats each prefix as "B827EB (base 16)"
        m = re.match(r"^([0-9A-Fa-f]{2})-([0-9A-Fa-f]{2})-([0-9A-Fa-f]{2})\s+\(hex\)\s+(.+)$", line)
        if m:  # IEEE oui.txt
            vendors["".join(m.group(1, 2, 3)).lower()] = m.group(4).strip()
            continue
        m = re.match(
            r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2})\s+(\S+)(?:\s+(.+))?$", line
        )
        if m:  # Wireshark manuf: short name, then the full name
            vendors["".join(m.group(1, 2, 3)).lower()] = (m.group(5) or m.group(4)).strip()
            continue
        m = re.match(r"^([0-9A-Fa-f]{6})\s+(.+)$", line)
        if m:  # nmap-mac-prefixes
            vendors[m.group(1).lower()] = m.group(2).strip()
    return vendors


def load_vendors(paths=_VENDOR_DBS) -> tuple[dict[str, str], str | None]:
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        vendors = parse_vendor_db(text)
        if vendors:
            return vendors, path
    return {}, None


# ── the neighbour (ARP) table ────────────────────────────────────────────────


def parse_proc_arp(text: str) -> dict[str, str]:
    """Linux /proc/net/arp → {ip: mac}, complete entries only."""
    table = {}
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4 and parts[2] != "0x0":
            mac = normalize_mac(parts[3])
            if mac:
                table[parts[0]] = mac
    return table


def parse_arp_an(text: str) -> dict[str, str]:
    """macOS / BSD `arp -an` → {ip: mac}."""
    table = {}
    for m in re.finditer(r"\((\d+\.\d+\.\d+\.\d+)\) at (\S+)", text):
        mac = normalize_mac(m.group(2))
        if mac:
            table[m.group(1)] = mac
    return table


def parse_arp_windows(text: str) -> dict[str, str]:
    """Windows `arp -a` → {ip: mac}."""
    table = {}
    for m in re.finditer(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+\w+", text, re.M):
        mac = normalize_mac(m.group(2))
        if mac:
            table[m.group(1)] = mac
    return table


def _run(*cmd: str) -> str:
    try:
        proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def neighbours() -> dict[str, str]:
    if sys.platform.startswith("linux"):
        try:
            return parse_proc_arp(Path("/proc/net/arp").read_text(encoding="utf-8"))
        except OSError:
            return {}
    if sys.platform == "win32":
        return parse_arp_windows(_run("arp", "-a"))
    return parse_arp_an(_run("arp", "-an"))


# ── which network ────────────────────────────────────────────────────────────


def _scoped_gateway(interface: str) -> str | None:
    """macOS: the router of *interface* even when a VPN owns the default route."""
    if sys.platform != "darwin":
        return None
    m = re.search(r"gateway:\s*(\S+)", _run("route", "-n", "get", "-ifscope", interface, "default"))
    return m.group(1) if m else None


def local_network() -> tuple[ipaddress.IPv4Interface, str, str | None, str | None] | None:
    """(address/prefix, interface, gateway, MAC) of the LAN this machine is on.
    The interface that holds the IPv4 default gateway wins; otherwise the
    first private, non-VPN one (a full-tunnel VPN owns the default route)."""
    info = net_diag.net(public=False, quiet=True)
    vpns = set(info.vpn_interfaces) | {
        i.name for i in info.interfaces if i.name.startswith(net_diag._VPN_PREFIXES)
    }
    candidates = []
    for iface in info.interfaces:
        if iface.loopback or iface.name in vpns or iface.state == "down":
            continue
        for text in iface.addresses:
            try:
                addr = ipaddress.ip_interface(text)
            except ValueError:
                continue
            if addr.version == 4 and addr.ip.is_private and not addr.ip.is_link_local:
                candidates.append((addr, iface))
    if not candidates:
        return None
    gateway = info.gateway_ipv4
    for addr, iface in candidates:
        if gateway and ipaddress.ip_address(gateway) in addr.network:
            return addr, iface.name, gateway, iface.mac
    addr, iface = candidates[0]
    return addr, iface.name, _scoped_gateway(iface.name), iface.mac


# ── probing and names ────────────────────────────────────────────────────────


def probe(hosts: list[str], rounds: int = 2) -> None:
    """One empty UDP datagram per address and round: the kernel has to ARP
    for each, which is all that is needed. Errors (no route, no buffer
    space) are expected for absent hosts and ignored."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setblocking(False)
        for _ in range(rounds):
            for i, host in enumerate(hosts):
                try:
                    sock.sendto(b"", (host, _DISCARD_PORT))
                except OSError:
                    pass  # no route / no buffer space: expected for absent hosts
                if i % 64 == 63:
                    time.sleep(0.01)  # don't overrun the ARP queue
            time.sleep(_SETTLE / rounds)


def device_name(ip: str, router: str | None) -> str | None:
    """Ask the device (mDNS), then the router's DNS (DHCP names)."""
    name = rdns_diag.query_ptr(ip, ip, port=5353, timeout=_NAME_TIMEOUT)
    if not name and router:
        name = rdns_diag.query_ptr(ip, router, timeout=_NAME_TIMEOUT)
    if name and name.endswith(".in-addr.arpa"):
        return None
    return name


def lan(
    network: str | None = None,
    scan: bool = True,
    names: bool = True,
    workers: int = 32,
    quiet: bool = False,
) -> LanResult:
    """Find the devices on *network* (default: this machine's LAN)."""
    result = LanResult()
    own_ip = own_mac = None
    found = local_network()
    if found:
        addr, result.interface, result.gateway, own_mac = found
        own_ip = str(addr.ip)
    if network:
        try:
            net = ipaddress.ip_network(network, strict=False)
        except ValueError:
            result.error = f"'{network}' is not a network (e.g. 192.168.1.0/24)"
        else:
            if net.version != 4:
                result.error = "only IPv4 networks have an ARP table to read"
            elif net.num_addresses > MAX_HOSTS:
                result.error = f"{net} has {net.num_addresses} addresses; the limit is {MAX_HOSTS}"
            result.network = str(net)
    elif found:
        net = addr.network
        if net.prefixlen < DEFAULT_MAX_PREFIX:  # scan the part around this machine
            net = ipaddress.ip_interface(f"{addr.ip}/{DEFAULT_MAX_PREFIX}").network
        result.network = str(net)
    else:
        result.error = "no private IPv4 network found on this machine (name one: 10.0.0.0/24)"

    if not quiet:
        print(section_header(f"LAN DEVICES  {result.network or ''}".rstrip(), "⌂"))
    if result.error or result.network is None:
        if not quiet:
            lan_view.print_result(result)
        return result

    net = ipaddress.ip_network(result.network)
    hosts = [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]
    spinner = None
    if not quiet and sys.stdout.isatty():
        what = f"Probing {len(hosts)} addresses…" if scan else "Reading the ARP table…"
        spinner = Spinner(c(what, BRAND_TEAL))
        spinner.start()
    try:
        if scan:
            probe([h for h in hosts if h != own_ip])
            result.scanned = len(hosts)
        table = {ip: mac for ip, mac in neighbours().items() if ipaddress.ip_address(ip) in net}
        if own_ip and ipaddress.ip_address(own_ip) in net:
            mac = normalize_mac(own_mac or "")
            table.setdefault(own_ip, mac or "")
        vendors, result.vendor_db = load_vendors()
        devices = []
        for ip, mac in table.items():
            if mac and _unusable(mac):
                continue
            device = LanDevice(
                ip=ip,
                mac=mac or None,
                is_self=ip == own_ip,
                is_gateway=ip == result.gateway,
            )
            if mac:
                device.random_mac = is_random_mac(mac)
                device.vendor = None if device.random_mac else vendors.get(mac.replace(":", "")[:6])
            devices.append(device)
        if names and devices:
            with ThreadPoolExecutor(max_workers=max(1, min(workers, len(devices)))) as pool:
                for device, name in zip(
                    devices,
                    pool.map(lambda d: device_name(d.ip, result.gateway), devices),
                    strict=True,
                ):
                    device.name = name
        result.devices = sorted(devices, key=lambda d: ipaddress.ip_address(d.ip))
    finally:
        if spinner:
            spinner.stop()

    if not quiet:
        lan_view.print_result(result)
    return result
