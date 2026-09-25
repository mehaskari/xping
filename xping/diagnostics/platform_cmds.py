"""Cross-platform system command builders for ping and traceroute."""

from __future__ import annotations

import platform
import re
import shutil


def system_name() -> str:
    return platform.system().lower()


def ping_command(target: str, timeout: float) -> list[str]:
    """Build a one-shot ping command for the current platform."""
    system = system_name()
    if system == "windows":
        wait_ms = max(1, int(timeout * 1000))
        return ["ping", "-n", "1", "-w", str(wait_ms), target]
    if system == "darwin":
        wait_ms = max(1, int(timeout * 1000))
        return ["ping", "-c", "1", "-W", str(wait_ms), target]
    wait_sec = max(1, int(timeout))
    return ["ping", "-c", "1", "-W", str(wait_sec), target]


def parse_ping_rtt(output: str) -> float:
    """Extract RTT in milliseconds from ping stdout/stderr."""
    match = re.search(r"time[=<]\s*([\d.]+)\s*ms", output, re.IGNORECASE)
    if match:
        return float(match.group(1))
    if re.search(r"time<\s*1\s*ms", output, re.IGNORECASE):
        return 1.0
    return -1.0


def trace_tool() -> str | None:
    """Return the available trace binary name, if any."""
    for name in ("traceroute", "tracert"):
        if shutil.which(name):
            return name
    return None


def trace_command(host: str, max_hops: int, probes: int, timeout: float = 2.0) -> list[str]:
    """Build a traceroute command for the current platform."""
    tool = trace_tool()
    if tool == "tracert":
        wait_ms = max(1, int(timeout * 1000))
        return ["tracert", "-h", str(max_hops), "-w", str(wait_ms), host]
    wait_sec = max(1, round(timeout))
    return ["traceroute", "-m", str(max_hops), "-q", str(probes), "-w", str(wait_sec), host]


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


def _parse_traceroute_line(line: str) -> tuple[int, list[float], str | None, str | None] | None:
    parts = line.split()
    if not parts or not parts[0].isdigit():
        return None

    ttl = int(parts[0])
    rtt_re = re.compile(r"([\d.]+)\s*ms|\*")
    rtts = [float(value) if value else -1.0 for value in rtt_re.findall(line)]
    ips = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", line)
    ip = ips[0] if ips else None
    match = re.search(r"([a-zA-Z][\w.\-]{3,})\s+\(?([\d.]{7,})\)?", line)
    hostname = match.group(1) if match else None
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

    ips = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", line)
    ip = ips[0] if ips else None
    hostname = None
    return ttl, rtts, ip, hostname


# ── Path MTU discovery ──────────────────────────────────────────────────────


def mtu_probe_command(target: str, payload_size: int, timeout: float) -> list[str]:
    """Build a one-shot, 'don't fragment'-flagged ping command of *payload_size*
    bytes for the current platform."""
    system = system_name()
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
