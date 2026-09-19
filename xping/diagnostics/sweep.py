"""
xping.sweep - Live TCP sweep for IP ranges and CIDR networks.
"""

import ipaddress
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from xping.diagnostics.portscan import scan_port
from xping.models.sweep import HostProbe, SweepResult
from xping.render import BRAND_INDIGO, c, kv, section_header
from xping.render.errors import error
from xping.render.views import sweep as sweep_view


def parse_targets(value: str, limit: int = 4096) -> list[str]:
    try:
        if "-" in value and "/" not in value:
            targets = _parse_ip_range(value, limit)
        else:
            network = ipaddress.ip_network(value, strict=False)
            targets = []
            for ip in network.hosts():
                if len(targets) >= limit:
                    raise ValueError(f"target range is too large (max {limit} hosts)")
                targets.append(str(ip))
            if not targets and network.num_addresses == 1:
                targets = [str(network.network_address)]
    except ValueError as exc:
        msg = str(exc)
        if "too large" in msg or "ascending" in msg or "same IP version" in msg:
            raise
        raise ValueError(f"invalid IP range or CIDR: {value}") from exc
    return targets


def _parse_ip_range(value: str, limit: int) -> list[str]:
    start_s, end_s = value.split("-", 1)
    start = ipaddress.ip_address(start_s.strip())
    end = ipaddress.ip_address(end_s.strip())
    if start.version != end.version:
        raise ValueError("range endpoints must use the same IP version")
    if int(start) > int(end):
        raise ValueError("IP ranges must be ascending")
    targets = []
    for item in range(int(start), int(end) + 1):
        if len(targets) >= limit:
            raise ValueError(f"target range is too large (max {limit} hosts)")
        targets.append(str(ipaddress.ip_address(item)))
    return targets


def _probe_host(ip: str, ports: list[int], timeout: float) -> HostProbe:
    started = time.perf_counter()
    open_ports = []
    for port in ports:
        result = scan_port(ip, port, timeout)
        if result.open:
            open_ports.append(port)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return HostProbe(ip=ip, open_ports=open_ports, elapsed_ms=elapsed_ms)


def sweep(
    target: str,
    ports: list[int],
    timeout: float = 0.5,
    workers: int = 128,
    limit: int = 4096,
    quiet: bool = False,
) -> SweepResult:
    try:
        hosts = parse_targets(target, limit=limit)
    except ValueError as exc:
        if not quiet:
            error(str(exc))
        return SweepResult(target=target, ports=ports, error=str(exc))

    if not quiet:
        print(section_header(f"IP SWEEP  {target}", "▥"))
        print(kv("Targets", f"{len(hosts)} hosts"))
        print(kv("Ports", c(",".join(str(port) for port in ports), BRAND_INDIGO)))
        print(kv("Timeout", f"{timeout}s / host-port"))
        print()

    probes: list[HostProbe] = []
    max_workers = max(1, min(workers, len(hosts)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_probe_host, ip, ports, timeout): ip for ip in hosts}
        for future in as_completed(futures):
            probe = future.result()
            probes.append(probe)
            if not quiet:
                sweep_view.print_probe(probe)

    probes.sort(key=lambda item: ipaddress.ip_address(item.ip))
    result = SweepResult(target=target, ports=ports, hosts=probes)
    if not quiet:
        sweep_view.print_summary(result)
    return result
