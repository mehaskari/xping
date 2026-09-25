"""
xping.diagnostics.net — your own network at a glance.

Interfaces (addresses, MTU, state), default gateway, DNS resolvers, the
local source addresses used for outbound traffic, and — unless
``--no-public`` — the public IPv4/IPv6 addresses the internet sees
(Cloudflare's /cdn-cgi/trace endpoint on 1.1.1.1 and its IPv6 twin).

Sources per platform, all stdlib + the OS's own tools:
  Linux    ip -o link / ip -o addr / ip route, /etc/resolv.conf
           (upstream servers from systemd-resolved when the stub is used)
  macOS    ifconfig, route -n get default, scutil --dns
  Windows  ipconfig /all  (English output)
"""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from xping.diagnostics.sslctx import secure_context
from xping.models.net import NetInterface, NetResult
from xping.render import BRAND_TEAL, c, section_header
from xping.render.animations import Spinner
from xping.render.views import net as net_view

_TRACE_V4 = "https://1.1.1.1/cdn-cgi/trace"
_TRACE_V6 = "https://[2606:4700:4700::1111]/cdn-cgi/trace"


def _run(*cmd: str) -> str | None:
    try:
        proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=6)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


# ── local source addresses ───────────────────────────────────────────────────


def local_address(family: int) -> str | None:
    """Source address the OS would use for outbound traffic. A UDP
    connect() only picks a route — no packet is sent."""
    target = ("2606:4700:4700::1111", 53) if family == socket.AF_INET6 else ("1.1.1.1", 53)
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.connect(target)
            return sock.getsockname()[0]
    except OSError:
        return None


# ── Linux ─────────────────────────────────────────────────────────────────────


def parse_ip_link(output: str) -> dict[str, NetInterface]:
    """Parse `ip -o link show`."""
    interfaces: dict[str, NetInterface] = {}
    for line in output.splitlines():
        m = re.match(r"^\d+:\s+([^:@\s]+)(?:@\S+)?:\s+<([^>]*)>(.*)$", line)
        if not m:
            continue
        name, flags, rest = m.group(1), m.group(2).split(","), m.group(3)
        iface = NetInterface(name=name)
        mtu = re.search(r"\bmtu (\d+)", rest)
        iface.mtu = int(mtu.group(1)) if mtu else None
        state = re.search(r"\bstate (\S+)", rest)
        if state and state.group(1) in ("UP", "DOWN"):
            iface.state = state.group(1).lower()
        elif "UP" in flags:
            iface.state = "up"
        mac = re.search(r"link/ether ([0-9a-f:]{17})", rest)
        iface.mac = mac.group(1) if mac else None
        interfaces[name] = iface
    return interfaces


def parse_ip_addr(output: str, interfaces: dict[str, NetInterface]) -> None:
    """Parse `ip -o addr show` into *interfaces* (created as needed)."""
    for line in output.splitlines():
        m = re.match(r"^\d+:\s+([^:@\s]+)(?:@\S+)?\s+inet6?\s+(\S+)", line)
        if m:
            iface = interfaces.setdefault(m.group(1), NetInterface(name=m.group(1)))
            iface.addresses.append(m.group(2))


def parse_ip_route(output: str) -> tuple[str | None, str | None]:
    """(gateway, interface) from `ip route show default`."""
    m = re.search(r"default via (\S+)(?:.*? dev (\S+))?", output)
    return (m.group(1), m.group(2)) if m else (None, None)


def parse_resolv_conf(text: str) -> list[str]:
    servers = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver" and parts[1] not in servers:
            servers.append(parts[1])
    return servers


def _linux(result: NetResult) -> None:
    interfaces = parse_ip_link(_run("ip", "-o", "link", "show") or "")
    parse_ip_addr(_run("ip", "-o", "addr", "show") or "", interfaces)
    result.interfaces = list(interfaces.values())
    result.gateway_ipv4, result.gateway_interface = parse_ip_route(
        _run("ip", "-4", "route", "show", "default") or ""
    )
    result.gateway_ipv6, _ = parse_ip_route(_run("ip", "-6", "route", "show", "default") or "")
    servers = _read_resolv("/etc/resolv.conf")
    # systemd-resolved stub (127.0.0.53): show the real upstream servers too
    if servers and all(s.startswith("127.0.0.5") for s in servers):
        servers += [s for s in _read_resolv("/run/systemd/resolve/resolv.conf") if s not in servers]
    result.dns_servers = servers


def _read_resolv(path: str) -> list[str]:
    try:
        return parse_resolv_conf(Path(path).read_text())
    except OSError:
        return []


# ── macOS / BSD ───────────────────────────────────────────────────────────────


def _netmask_bits(mask: str) -> int | None:
    try:
        value = int(mask, 16) if mask.startswith("0x") else int(ipaddress.IPv4Address(mask))
    except ValueError:
        return None
    return bin(value).count("1")


def parse_ifconfig(output: str) -> list[NetInterface]:
    """Parse BSD/macOS `ifconfig` output."""
    interfaces: list[NetInterface] = []
    current: NetInterface | None = None
    for line in output.splitlines():
        header = re.match(r"^(\S+?):\s+flags=\d+<([^>]*)>.*?(?:mtu (\d+))?\s*$", line)
        if header:
            current = NetInterface(name=header.group(1))
            current.state = "up" if "UP" in header.group(2).split(",") else "down"
            current.mtu = int(header.group(3)) if header.group(3) else None
            interfaces.append(current)
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("inet "):
            parts = stripped.split()
            bits = None
            if "netmask" in parts:
                bits = _netmask_bits(parts[parts.index("netmask") + 1])
            current.addresses.append(f"{parts[1]}/{bits}" if bits is not None else parts[1])
        elif stripped.startswith("inet6 "):
            parts = stripped.split()
            addr = parts[1].split("%", 1)[0]
            if "prefixlen" in parts:
                addr += f"/{parts[parts.index('prefixlen') + 1]}"
            current.addresses.append(addr)
        elif stripped.startswith("ether "):
            current.mac = stripped.split()[1]
        elif stripped.startswith("status:") and "inactive" in stripped:
            current.state = "down"
    return interfaces


def parse_route_get(output: str) -> tuple[str | None, str | None]:
    """(gateway, interface) from macOS `route -n get default`."""
    gateway = re.search(r"gateway:\s*(\S+)", output)
    iface = re.search(r"interface:\s*(\S+)", output)
    return (gateway.group(1) if gateway else None, iface.group(1) if iface else None)


def parse_scutil_dns(output: str) -> list[str]:
    servers: list[str] = []
    for m in re.finditer(r"nameserver\[\d+\]\s*:\s*(\S+)", output):
        if m.group(1) not in servers:
            servers.append(m.group(1))
    return servers


def _darwin(result: NetResult) -> None:
    result.interfaces = parse_ifconfig(_run("ifconfig") or "")
    result.gateway_ipv4, result.gateway_interface = parse_route_get(
        _run("route", "-n", "get", "default") or ""
    )
    gw6, _ = parse_route_get(_run("route", "-n", "get", "-inet6", "default") or "")
    result.gateway_ipv6 = gw6.split("%", 1)[0] if gw6 else None
    result.dns_servers = parse_scutil_dns(_run("scutil", "--dns") or "") or _read_resolv(
        "/etc/resolv.conf"
    )


# ── Windows ───────────────────────────────────────────────────────────────────


def parse_ipconfig(output: str) -> tuple[list[NetInterface], list[str], list[str]]:
    """Parse English `ipconfig /all`: (interfaces, gateways, dns servers)."""
    interfaces: list[NetInterface] = []
    gateways: list[str] = []
    dns: list[str] = []
    current: NetInterface | None = None
    last_key = ""
    for raw in output.splitlines():
        if raw and not raw.startswith(" ") and raw.rstrip().endswith(":"):
            name = raw.rstrip().rstrip(":")
            name = re.sub(r"^.*? adapter ", "", name)
            current = NetInterface(name=name, state="up")
            interfaces.append(current)
            last_key = ""
            continue
        if current is None or not raw.strip():
            continue
        m = re.match(r"^\s+([^:]+?)[ .]*:\s*(.*)$", raw)
        if m:
            last_key, value = m.group(1).strip().lower(), m.group(2).strip()
        else:
            value = raw.strip()  # continuation line (extra DNS servers, …)
        value = re.sub(r"\((Preferred|Deprecated|Tentative)\)$", "", value).strip()
        if not value:
            continue
        if last_key.startswith("media state") and "disconnected" in value.lower():
            current.state = "down"
        elif last_key.startswith(("ipv4 address", "ip address")):
            current.addresses.append(value)
        elif "ipv6 address" in last_key:
            current.addresses.append(value.split("%", 1)[0])
        elif last_key.startswith("physical address"):
            current.mac = value.replace("-", ":").lower()
        elif last_key.startswith("default gateway") and value not in gateways:
            gateways.append(value.split("%", 1)[0])
        elif last_key.startswith("dns servers") and value not in dns:
            dns.append(value.split("%", 1)[0])
    return interfaces, gateways, dns


def _windows(result: NetResult) -> None:
    interfaces, gateways, dns = parse_ipconfig(_run("ipconfig", "/all") or "")
    result.interfaces = interfaces
    result.dns_servers = dns
    for gw in gateways:
        if ":" in gw:
            result.gateway_ipv6 = result.gateway_ipv6 or gw
        else:
            result.gateway_ipv4 = result.gateway_ipv4 or gw


# ── public addresses ──────────────────────────────────────────────────────────


def parse_cf_trace(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def _cf_trace(url: str) -> dict[str, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "xping/net"})
        with urllib.request.urlopen(req, context=secure_context(), timeout=4) as resp:
            return parse_cf_trace(resp.read(4096).decode("utf-8", "replace"))
    except Exception:
        return {}  # offline, blocked, or no IPv6 route — reported as "—"


def net(public: bool = True, quiet: bool = False, show_all: bool = False) -> NetResult:
    """Collect the local network overview."""
    result = NetResult(hostname=socket.gethostname())

    if not quiet:
        print(section_header("NETWORK OVERVIEW", "◉"))
        print()

    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Inspecting interfaces, routes and resolvers…", BRAND_TEAL))
        spinner.start()

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            v4 = pool.submit(_cf_trace, _TRACE_V4) if public else None
            v6 = pool.submit(_cf_trace, _TRACE_V6) if public else None
            if sys.platform == "win32":
                _windows(result)
            elif sys.platform == "darwin":
                _darwin(result)
            else:
                _linux(result)
            result.local_ipv4 = local_address(socket.AF_INET)
            result.local_ipv6 = local_address(socket.AF_INET6)
            if v4 is not None and v6 is not None:
                t4, t6 = v4.result(), v6.result()
                result.public_ipv4 = t4.get("ip")
                result.public_ipv6 = t6.get("ip")
                result.location = t4.get("loc") or t6.get("loc")
                result.colo = t4.get("colo") or t6.get("colo")
    finally:
        if spinner:
            spinner.stop()

    if not result.interfaces and not result.local_ipv4 and not result.local_ipv6:
        result.error = "Could not determine any network configuration"

    if not quiet:
        net_view.print_result(result, public=public, show_all=show_all)
    return result
