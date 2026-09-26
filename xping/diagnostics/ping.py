"""
xping.ping — Live animated ICMP ping.
Each reply is printed the moment it arrives — no buffering.
"""

import socket
import subprocess
import sys
import time

from xping.diagnostics import icmp
from xping.diagnostics.deps import is_available, require, warn_missing
from xping.diagnostics.platform_cmds import parse_ping_rtt, ping_command
from xping.diagnostics.resolve import resolve
from xping.models.ping import PingResult
from xping.render import (
    BOLD,
    BRAND_INDIGO,
    BRAND_TEAL,
    c,
    kv,
    section_header,
)
from xping.render.animations import Spinner
from xping.render.errors import resolve_error
from xping.render.views import ping as ping_view


def _icmp_ping(host: str, seq: int, timeout: float = 2.0) -> float | None:
    """One native ICMP/ICMPv6 echo. Returns RTT ms, -1.0 on timeout, or None
    when no ICMP socket can be opened (neither unprivileged nor raw)."""
    return icmp.echo(resolve(host), seq, timeout)


def _subprocess_ping_one(host: str, timeout: float) -> float:
    """System ping, one packet. Returns RTT ms or -1."""
    try:
        proc = subprocess.run(
            ping_command(host, timeout),
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return parse_ping_rtt(output)
    except Exception:
        return -1.0


def ping_once(host_ip: str, seq: int, timeout: float = 2.0) -> float | None:
    """Public single-probe wrapper (used by `mtr`). Returns RTT ms, -1.0 on
    timeout, or None if raw sockets are unavailable."""
    return _icmp_ping(host_ip, seq, timeout)


def ping_once_subprocess(host_ip: str, timeout: float = 2.0) -> float:
    """Public single-probe wrapper around the system `ping` fallback."""
    return _subprocess_ping_one(host_ip, timeout)


def ping(
    host: str,
    count: int = 5,
    timeout: float = 2.0,
    interval: float = 0.5,
    quiet: bool = False,
    family: int | None = None,
) -> PingResult:

    try:
        ip = resolve(host, family)
    except socket.gaierror as exc:
        if not quiet:
            resolve_error(host, exc if family else None)
        return PingResult(host=host, ip="?", count=count, resolved=False)

    if not quiet:
        print(section_header(f"PING  {host}", "◉"))
        print(kv("Target", c(host, BRAND_TEAL, BOLD)))
        print(kv("IP", c(ip, BRAND_INDIGO)))
        print(kv("Packets", str(count)))
        print(kv("Interval", f"{interval}s"))
        print(kv("Timeout", f"{timeout}s / packet"))
        print()

    rtts: list[float] = []
    use_subprocess = False

    try:
        for seq in range(1, count + 1):
            spinner = None
            if not quiet and sys.stdout.isatty():
                spinner_label = c(f"Waiting for reply #{seq}", BRAND_TEAL)
                spinner = Spinner(spinner_label)
                spinner.start()

            t0 = time.perf_counter()

            if use_subprocess:
                rtt = _subprocess_ping_one(ip, timeout)
            else:
                rtt = _icmp_ping(ip, seq, timeout)
                if rtt is None:
                    use_subprocess = True
                    if not is_available("ping"):
                        if spinner:
                            spinner.stop()
                        require("ping", "ICMP ping fallback")
                        return PingResult(host=host, ip=ip, count=count)
                    if not quiet:
                        if spinner:
                            spinner.stop()
                        warn_missing(
                            "raw sockets", "using system ping (run as root for native mode)"
                        )
                        spinner = None
                    rtt = _subprocess_ping_one(ip, timeout)

            elapsed = time.perf_counter() - t0

            if spinner:
                spinner.stop()

            rtts.append(rtt)
            if not quiet:
                ping_view.print_line(seq, ip, rtt, count)

            if seq < count:
                remaining = interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)

    except KeyboardInterrupt:
        if spinner:
            spinner.stop()
        print()

    result = PingResult(host=host, ip=ip, count=count, rtts=rtts)
    if not quiet:
        ping_view.print_summary(result)
    return result


DOWN_AFTER_LOSSES = 3  # consecutive lost pings before --notify reports "down"


def watch(
    host: str,
    timeout: float = 2.0,
    interval: float = 1.0,
    family: int | None = None,
    notifier=None,
) -> None:
    """Continuous live ping with in-place sparkline (Ctrl-C to stop).

    With a *notifier*, the host counts as down after DOWN_AFTER_LOSSES
    consecutive lost pings and as up again at the next reply — a single
    lost packet is not an outage."""
    try:
        ip = resolve(host, family)
    except socket.gaierror:
        from xping.render.errors import resolve_error

        resolve_error(host)
        return

    from xping.render import BOLD, BRAND_INDIGO, BRAND_TEAL, c, kv, section_header

    print(section_header(f"PING WATCH  {host}", "◉"))
    print(kv("Target", c(host, BRAND_TEAL, BOLD)))
    print(kv("IP", c(ip, BRAND_INDIGO)))
    print(kv("Interval", f"{interval}s"))
    print(kv("Stop", "Ctrl-C"))
    print()

    rtts: list[float] = []
    use_subprocess = False
    printed_rows = 0
    state: bool | None = None  # up/down as reported to the notifier
    losses = 0

    try:
        seq = 0
        while True:
            seq += 1
            t0 = time.perf_counter()

            if use_subprocess:
                rtt = _subprocess_ping_one(ip, timeout)
            else:
                rtt = _icmp_ping(ip, seq, timeout)
                if rtt is None:
                    use_subprocess = True
                    rtt = _subprocess_ping_one(ip, timeout)

            elapsed = time.perf_counter() - t0
            rtts.append(rtt)
            printed_rows = ping_view.redraw_watch(rtts, printed_rows)
            if notifier is not None:
                losses = 0 if rtt >= 0 else losses + 1
                new_state = True if rtt >= 0 else False if losses >= DOWN_AFTER_LOSSES else state
                if new_state is not None:
                    detail = (
                        f"reply in {rtt:.1f} ms" if new_state else f"{losses} pings lost in a row"
                    )
                    notifier.observe(new_state, state, detail, rtt if rtt >= 0 else None)
                    state = new_state

            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print()
        result = PingResult(host=host, ip=ip, count=len(rtts), rtts=rtts)
        ping_view.print_summary(result)
    finally:
        if notifier is not None:
            notifier.flush()
