"""
xping.diagnostics.listen — Show locally listening TCP/UDP ports.
Uses ss (Linux), netstat (macOS/Linux/Windows). No external libs.
"""

import re
import subprocess
import sys

from xping.models.listen import ListenEntry, ListenResult
from xping.render import section_header
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
            m = re.match(r"\[(.+)\]:(\d+)", local)
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
        entries.append(
            ListenEntry(proto=proto, local_addr=addr or "*", local_port=port, pid=pid, process=proc)
        )
    return entries


def _split_addr(local: str) -> tuple[str, int] | None:
    """Split a netstat local address into (addr, port).

    Handles Linux (0.0.0.0:22, :::22, [::]:22) and BSD/macOS, which separate
    the port with a dot (*.22, 127.0.0.1.631, ::1.631, fe80::1%lo0.123).
    The port delimiter is whichever of '.' or ':' comes last."""
    m = re.match(r"^\[(.+)\]:(\d+)$", local)
    if m:
        addr, port_s = m.group(1), m.group(2)
    else:
        cut = max(local.rfind("."), local.rfind(":"))
        if cut < 0:
            return None
        addr, port_s = local[:cut], local[cut + 1 :]
    try:
        return addr or "*", int(port_s)
    except ValueError:
        return None


def _parse_netstat_unix(output: str) -> list[ListenEntry]:
    """Parse Linux `netstat -tlunp` or macOS/BSD `netstat -an` output."""
    entries = []
    for line in output.splitlines():
        parts = line.split()
        # Linux: tcp, tcp6, udp, udp6 — macOS/BSD: tcp4, tcp6, tcp46, udp4, …
        if len(parts) < 5 or not re.match(r"^(tcp|udp)(4|6|46)?$", parts[0]):
            continue
        proto = "tcp" if parts[0].startswith("tcp") else "udp"
        foreign = parts[4]
        if proto == "tcp":
            if len(parts) < 6 or parts[5] != "LISTEN":
                continue
        elif not foreign.endswith("*"):
            continue  # connected UDP socket, not a listener
        pid, proc = None, None
        for token in parts[5:]:
            m = re.match(r"^(\d+)/(.+)$", token)
            if m:
                pid, proc = int(m.group(1)), m.group(2)
                break
        addr_port = _split_addr(parts[3])
        if addr_port is None:
            continue
        addr, port = addr_port
        entries.append(
            ListenEntry(proto=proto, local_addr=addr, local_port=port, pid=pid, process=proc)
        )
    return entries


def _parse_netstat_windows(output: str) -> list[ListenEntry]:
    """Parse Windows `netstat -an` output."""
    entries = []
    for line in output.splitlines():
        parts = line.split()
        # TCP rows have a state column; UDP rows have only 3 columns
        if len(parts) < 3:
            continue
        if parts[0] not in ("TCP", "UDP"):
            continue
        proto = parts[0].lower()
        local = parts[1]
        state = parts[3] if proto == "tcp" and len(parts) >= 4 else "LISTENING"
        if proto == "tcp" and "LISTENING" not in state:
            continue
        addr_port = _split_addr(local)
        if addr_port is None:
            continue
        addr, port = addr_port
        entries.append(ListenEntry(proto=proto, local_addr=addr, local_port=port))
    return entries


def listen(proto_filter: str | None = None, quiet: bool = False) -> ListenResult:
    """Show locally listening TCP/UDP ports."""
    result = ListenResult()

    if not quiet:
        title = "LISTENING PORTS"
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
            # GNU netstat understands -tlunp; BSD/macOS netstat does not
            # (it lists UNIX sockets instead), so ask for everything there.
            flags = "-tlunp" if platform.startswith("linux") else "-an"
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
