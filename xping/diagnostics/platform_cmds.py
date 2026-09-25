"""Cross-platform system command builders for ping and traceroute."""

from __future__ import annotations

import ipaddress
import platform
import re
import shutil

from xping.diagnostics.resolve import is_ipv6


def system_name() -> str:
    return platform.system().lower()


def ping_command(target: str, timeout: float) -> list[str]:
    """Build a one-shot ping command for the current platform.

    IPv6 literals get the platform's IPv6 form: ``ping -6`` on Linux and
    Windows, ``ping6`` on macOS (which has no per-reply timeout flag — the
    caller's subprocess timeout bounds it instead).
    """
    system = system_name()
    v6 = is_ipv6(target)
    if system == "windows":
        wait_ms = max(1, int(timeout * 1000))
        return ["ping", *(["-6"] if v6 else []), "-n", "1", "-w", str(wait_ms), target]
    if system == "darwin":
        if v6:
            return ["ping6", "-c", "1", target]
        wait_ms = max(1, int(timeout * 1000))
        return ["ping", "-c", "1", "-W", str(wait_ms), target]
    wait_sec = max(1, int(timeout))
    return ["ping", *(["-6"] if v6 else []), "-c", "1", "-W", str(wait_sec), target]


def parse_ping_rtt(output: str) -> float:
    """Extract RTT in milliseconds from ping stdout/stderr."""
    match = re.search(r"time[=<]\s*([\d.]+)\s*ms", output, re.IGNORECASE)
    if match:
        return float(match.group(1))
    if re.search(r"time<\s*1\s*ms", output, re.IGNORECASE):
        return 1.0
    return -1.0


def trace_tool(ipv6: bool = False) -> str | None:
    """Return the available trace binary name, if any."""
    names = ("traceroute6", "traceroute", "tracert") if ipv6 else ("traceroute", "tracert")
    for name in names:
        if shutil.which(name):
            return name
    return None


def trace_command(host: str, max_hops: int, probes: int, timeout: float = 2.0) -> list[str]:
    """Build a traceroute command for the current platform.

    An IPv6 literal *host* selects ``traceroute6`` (macOS/BSD),
    ``traceroute -6`` (Linux) or ``tracert -6`` (Windows).
    """
    v6 = is_ipv6(host)
    tool = trace_tool(v6)
    if tool == "tracert":
        wait_ms = max(1, int(timeout * 1000))
        return ["tracert", *(["-6"] if v6 else []), "-h", str(max_hops), "-w", str(wait_ms), host]
    wait_sec = max(1, round(timeout))
    base = ["traceroute6"] if tool == "traceroute6" else ["traceroute", *(["-6"] if v6 else [])]
    return [*base, "-m", str(max_hops), "-q", str(probes), "-w", str(wait_sec), host]


def parse_trace_line(line: str) -> tuple[int, list[float], str | None, str | None] | None:
    """
    Parse one traceroute/tracert output line.

    Returns (ttl, rtts, ip, hostname) or None when the line is not a hop row.
    """
    line = line.strip()
    if not line:
        return None

    if system_name() == "windows":
        return _parse_tracert_line(line)
    return _parse_traceroute_line(line)


def _first_ip(line: str) -> str | None:
    """First IPv4 or IPv6 address in a traceroute line (brackets/parens ok)."""
    for token in line.split():
        candidate = token.strip("()[],")
        if ":" not in candidate and candidate.count(".") != 3:
            continue
        try:
            ipaddress.ip_address(candidate.split("%", 1)[0])
        except ValueError:
            continue
        return candidate
    return None


def _parse_traceroute_line(line: str) -> tuple[int, list[float], str | None, str | None] | None:
    parts = line.split()
    if not parts or not parts[0].isdigit():
        return None

    ttl = int(parts[0])
    rtt_re = re.compile(r"([\d.]+)\s*ms|\*")
    rtts = [float(value) if value else -1.0 for value in rtt_re.findall(line)]
    ip = _first_ip(line)
    match = re.search(r"([a-zA-Z][\w.\-]{3,})\s+\(?([\d.]{7,})\)?", line) or re.search(
        r"([a-zA-Z][\w.\-]{3,})\s+\(([0-9a-fA-F:.%]+)\)", line
    )
    hostname = match.group(1) if match and match.group(1) != ip else None
    return ttl, rtts, ip, hostname


def _parse_tracert_line(line: str) -> tuple[int, list[float], str | None, str | None] | None:
    match = re.match(r"^\s*(\d+)\s+", line)
    if not match:
        return None

    ttl = int(match.group(1))
    rtts: list[float] = []
    for probe in re.finditer(r"<?(\d+)\s*ms|\*", line, re.IGNORECASE):
        if probe.group(1):
            rtts.append(float(probe.group(1)))
        else:
            rtts.append(-1.0)
    if not rtts:
        rtts = [-1.0, -1.0, -1.0]

    ip = _first_ip(line)
    hostname = None
    return ttl, rtts, ip, hostname


# ── Path MTU discovery ──────────────────────────────────────────────────────


def mtu_probe_command(target: str, payload_size: int, timeout: float) -> list[str]:
    """Build a one-shot, 'don't fragment'-flagged ping command of *payload_size*
    bytes for the current platform.

    IPv6 routers never fragment, so for IPv6 only local fragmentation has to
    be disabled: ``ping -6 -M do`` on Linux, ``ping6 -m`` on macOS. Windows'
    ``-f`` flag is IPv4-only, so IPv6 MTU discovery raises there.
    """
    system = system_name()
    if is_ipv6(target):
        if system == "windows":
            raise ValueError("IPv6 path MTU discovery is not supported on Windows")
        if system == "darwin":
            return ["ping6", "-m", "-s", str(payload_size), "-c", "1", target]
        wait_sec = max(1, int(timeout))
        return [
            "ping",
            "-6",
            "-M",
            "do",
            "-s",
            str(payload_size),
            "-c",
            "1",
            "-W",
            str(wait_sec),
            target,
        ]
    if system == "windows":
        wait_ms = max(1, int(timeout * 1000))
        return ["ping", "-f", "-l", str(payload_size), "-n", "1", "-w", str(wait_ms), target]
    if system == "darwin":
        wait_sec = max(1, int(timeout))
        return ["ping", "-D", "-s", str(payload_size), "-c", "1", "-t", str(wait_sec), target]
    wait_sec = max(1, int(timeout))
    return ["ping", "-M", "do", "-s", str(payload_size), "-c", "1", "-W", str(wait_sec), target]


_FRAG_NEEDED_RE = re.compile(
    r"frag(?:mentation)?\s*needed|message too long|"
    r"packet needs to be fragmented|local error|would fragment",
    re.IGNORECASE,
)
_REPLY_RE = re.compile(r"time[=<]\s*[\d.]+\s*ms|bytes from", re.IGNORECASE)


def mtu_probe_succeeded(output: str) -> bool:
    """
    Best-effort read of a DF-flagged ping probe's output.

    Returns False whenever the probe was blocked by fragmentation (explicit
    ICMP 'fragmentation needed' message) or produced no reply at all, and
    True only when an actual echo reply was observed — meaning the packet
    crossed the path unfragmented.
    """
    if _FRAG_NEEDED_RE.search(output):
        return False
    return bool(_REPLY_RE.search(output))
