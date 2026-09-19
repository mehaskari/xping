"""
xping.ipscan - Live network host discovery over IP ranges.
"""

import ipaddress
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from xping.diagnostics.deps import require
from xping.diagnostics.platform_cmds import parse_ping_rtt, ping_command
from xping.diagnostics.sweep import parse_targets
from xping.models.ipscan import IpProbe, IpScanResult
from xping.render import BRAND_INDIGO, c, kv, section_header
from xping.render.errors import error
from xping.render.views import ipscan as ipscan_view


def _probe_ip(ip: str, timeout: float) -> IpProbe:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            ping_command(ip, timeout),
            capture_output=True,
            text=True,
            timeout=timeout + 1,
        )
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return IpProbe(ip=ip, alive=False, elapsed_ms=elapsed_ms, error="timeout")
    except OSError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return IpProbe(ip=ip, alive=False, elapsed_ms=elapsed_ms, error=str(exc))

    elapsed_ms = (time.perf_counter() - started) * 1000
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    rtt = parse_ping_rtt(output)
    alive = proc.returncode == 0
    probe_error = None
    if not alive:
        lowered = output.lower()
        if "operation not permitted" in lowered or "permission denied" in lowered:
            probe_error = "ping not permitted"
        elif "unknown host" in lowered or "could not find host" in lowered:
            probe_error = "host unavailable"
        else:
            probe_error = "no reply"
    return IpProbe(
        ip=ip,
        alive=alive,
        elapsed_ms=elapsed_ms,
        rtt_ms=rtt,
        error=probe_error,
    )


def ipscan(
    target: str, timeout: float = 1.0, workers: int = 128, limit: int = 4096, quiet: bool = False
) -> IpScanResult:
    try:
        hosts = parse_targets(target, limit=limit)
    except ValueError as exc:
        if not quiet:
            error(str(exc))
        return IpScanResult(target=target, error=str(exc))

    if not hosts:
        return IpScanResult(target=target, error="no hosts to scan")

    if not quiet:
        print(section_header(f"IP SCAN  {target}", "▤"))
        print(kv("Targets", f"{len(hosts)} IPs"))
        print(kv("Probe", c("ICMP echo via system ping", BRAND_INDIGO)))
        print(kv("Timeout", f"{timeout}s / IP"))
        print()

    if not require("ping", "IP scan host discovery"):
        return IpScanResult(target=target, error="'ping' not found")

    probes: list[IpProbe] = []
    max_workers = max(1, min(workers, len(hosts)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_probe_ip, ip, timeout): ip for ip in hosts}
        for future in as_completed(futures):
            probe = future.result()
            probes.append(probe)
            if not quiet:
                ipscan_view.print_probe(probe)

    probes.sort(key=lambda probe: ipaddress.ip_address(probe.ip))
    result = IpScanResult(target=target, probes=probes)
    if not quiet:
        ipscan_view.print_summary(result)
    return result
