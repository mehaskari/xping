"""
xping.diagnostics.listen — Show locally listening TCP/UDP ports.
Uses ss (Linux), netstat (macOS/Linux/Windows). No external libs.
"""

import re
import subprocess
import sys

from xping.models.listen import ListenEntry, ListenResult
from xping.render import BOLD, BRAND_TEAL, c, section_header
from xping.render.errors import error as render_error
from xping.render.views import listen as listen_view


def _run(*cmd: str) -> str | None:
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=8)
        return r.stdout if r.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _parse_ss(output: str) -> list[ListenEntry]:
    """Parse `ss -tlunp` output."""
    entries = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("Netid") or line.startswith("State"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        proto = parts[0].lower()
        if proto not in ("tcp", "udp"):
            continue
        local = parts[4]
        pid, proc = None, None
        # users:(("sshd",pid=1234,fd=3))
        users_match = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        if users_match:
            proc = users_match.group(1)
            pid = int(users_match.group(2))
        # parse addr:port
        if local.startswith("["):
            # IPv6 [::]:22
            m = re.match(r'\[(.+)\]:(\d+)', local)
            if m:
                addr, port_s = m.group(1), m.group(2)
            else:
                continue
        elif ":" in local:
            addr, _, port_s = local.rpartition(":")
        else:
            continue
        try:
            port = int(port_s)
        except ValueError:
            continue
        entries.append(ListenEntry(proto=proto, local_addr=addr or "*",
                                   local_port=port, pid=pid, process=proc))
    return entries


def _parse_netstat_unix(output: str) -> list[ListenEntry]:
    """Parse macOS/Linux `netstat -tlunp` output."""
    entries = []
    for line in output.splitlines():
        parts = line.split()
        if not parts or parts[0] not in ("tcp", "tcp6", "udp", "udp6"):
            continue
        if len(parts) < 6:
            continue
        state = parts[-1] if parts[0].startswith("tcp") else "LISTEN"
        if "LISTEN" not in state:
            continue
        local = parts[3]
        proto = "tcp" if parts[0].startswith("tcp") else "udp"
        pid_prog = parts[-2] if len(parts) >= 7 else "-"
        pid, proc = None, None
        if "/" in pid_prog:
            pid_s, proc = pid_prog.split("/", 1)
            try: pid = int(pid_s)
            except ValueError: pass
        if local.startswith("["):
            m = re.match(r'\[(.+)\]:(\d+)', local)
            if m: addr, port_s = m.group(1), m.group(2)
            else: continue
        elif "." in local:
            # macOS uses dots: 0.0.0.0.22
            parts2 = local.rsplit(".", 1)
            addr, port_s = parts2[0], parts2[1]
        elif ":" in local:
            addr, _, port_s = local.rpartition(":")
        else:
            continue
        try: port = int(port_s)
        except ValueError: continue
        entries.append(ListenEntry(proto=proto, local_addr=addr or "*",
                                   local_port=port, pid=pid, process=proc))
    return entries


def _parse_netstat_windows(output: str) -> list[ListenEntry]:
    """Parse Windows `netstat -an` output."""
    entries = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4: continue
        if parts[0] not in ("TCP", "UDP"): continue
        proto = parts[0].lower()
        local = parts[1]
        state = parts[3] if proto == "tcp" and len(parts) >= 4 else "LISTENING"
        if proto == "tcp" and "LISTENING" not in state: continue
        if ":" in local:
            addr, _, port_s = local.rpartition(":")
        else:
            continue
        try: port = int(port_s)
        except ValueError: continue
        entries.append(ListenEntry(proto=proto, local_addr=addr or "*",
                                   local_port=port))
    return entries


def listen(proto_filter: str | None = None, quiet: bool = False) -> ListenResult:
    """Show locally listening TCP/UDP ports."""
    result = ListenResult()

    if not quiet:
        title = f"LISTENING PORTS"
        if proto_filter:
            title += f"  ({proto_filter.upper()})"
        print(section_header(title, "◌"))
        print()

    entries: list[ListenEntry] = []
    platform = sys.platform

    if platform == "win32":
        out = _run("netstat", "-an")
        if out:
            entries = _parse_netstat_windows(out)
        else:
            result.error = "netstat not available"
    else:
        # Try ss first (Linux), then netstat (macOS/Linux)
        out = _run("ss", "-tlunp")
        if out:
            entries = _parse_ss(out)
        else:
            flags = "-tlunp" if platform.startswith("linux") else "-tlun"
            out = _run("netstat", flags)
            if out:
                entries = _parse_netstat_unix(out)
            else:
                result.error = "Neither ss nor netstat is available"

    if result.error:
        if not quiet:
            render_error(result.error)
        return result

    # Filter by protocol
    if proto_filter:
        pf = proto_filter.lower()
        entries = [e for e in entries if e.proto == pf]

    # Sort by port
    entries.sort(key=lambda e: (e.proto, e.local_port))
    # Deduplicate (same port/proto may appear for IPv4 and IPv6)
    seen: set[tuple] = set()
    unique = []
    for e in entries:
        key = (e.proto, e.local_port, e.process)
        if key not in seen:
            seen.add(key)
            unique.append(e)
    result.entries = unique

    if not quiet:
        listen_view.print_result(result)
    return result
