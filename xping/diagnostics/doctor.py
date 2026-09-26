"""
xping.diagnostics.doctor — "why is my internet not working?"

Walks the path from this machine outwards and stops guessing as soon as
something breaks:

  1. interface    an active interface with a real (non link-local) address
  2. gateway      a default route, and whether the router answers ping
  3. internet     TCP to well-known anycast IPs — no DNS involved
  4. dns          the system resolver; on failure, a direct query to a
                  public resolver tells "your DNS is broken" apart from
                  "DNS traffic is blocked"
  5. quality      packet loss / latency to 1.1.1.1
  6. captive      a Wi-Fi login page intercepting plain HTTP
  7. https        a verified TLS request; Cloudflare's timestamp also
                  reveals a wrong system clock
  8. ipv6         informational — IPv6 being absent is not an error
  9. target       optional: the host the user actually cares about

The result ends with one plain-language diagnosis plus what to do.
Contacts: 1.1.1.1, 8.8.8.8, 9.9.9.9 (TCP 443 / ICMP / DNS),
captive.apple.com (HTTP) and www.cloudflare.com (HTTPS).
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from xping.diagnostics import icmp
from xping.diagnostics import net as net_diag
from xping.diagnostics.lookup import _QTYPES, _raw_query
from xping.diagnostics.platform_cmds import parse_ping_rtt, ping_command
from xping.diagnostics.sslctx import secure_context
from xping.models.doctor import FAIL, INFO, OK, SKIP, WARN, DoctorResult, DoctorStep
from xping.models.net import NetResult
from xping.render import BRAND_TEAL, c, section_header
from xping.render.animations import Spinner
from xping.render.views import doctor as doctor_view

ANYCAST_V4 = ("1.1.1.1", "8.8.8.8", "9.9.9.9")
ANYCAST_V6 = "2606:4700:4700::1111"
PROBE_NAMES = ("cloudflare.com", "google.com")
CAPTIVE_HOST, CAPTIVE_PATH = "captive.apple.com", "/hotspot-detect.html"
TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
CLOCK_SKEW_WARN_S = 120
TIMEOUT = 3.0


# ── probes (module-level so tests can replace them) ──────────────────────────


def network_info() -> NetResult:
    return net_diag.net(public=False, quiet=True)


def ping_ip(ip: str, count: int = 3, timeout: float = 1.5) -> list[float]:
    """RTTs in ms (-1.0 = lost). Native ICMP, else the system ping."""
    rtts = []
    for seq in range(1, count + 1):
        rtt = icmp.echo(ip, seq, timeout)
        if rtt is None:  # no ICMP socket: one system ping per probe
            try:
                proc = subprocess.run(
                    ping_command(ip, timeout), capture_output=True, text=True, timeout=timeout + 2
                )
                rtt = parse_ping_rtt((proc.stdout or "") + (proc.stderr or ""))
            except (OSError, subprocess.SubprocessError):
                rtt = -1.0
        rtts.append(rtt)
    return rtts


def tcp_connect(ip: str, port: int = 443, timeout: float = TIMEOUT) -> float | None:
    """Connect time in ms, or None when the connection failed."""
    started = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return (time.perf_counter() - started) * 1000
    except OSError:
        return None


def system_resolve(name: str, timeout: float = 5.0) -> tuple[str | None, float]:
    """Resolve *name* with the OS resolver, bounded by *timeout*.
    Returns (first address or None, elapsed ms)."""
    started = time.perf_counter()
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(socket.getaddrinfo, name, 443, 0, socket.SOCK_STREAM)
    try:
        infos = future.result(timeout=timeout)
        address = infos[0][4][0] if infos else None
    except (FutureTimeout, OSError):
        address = None
    finally:
        pool.shutdown(wait=False)
    return address, (time.perf_counter() - started) * 1000


def direct_dns(name: str, server: str = "1.1.1.1") -> bool:
    """Does a public resolver answer an A query directly (UDP 53)?"""
    status, records = _raw_query(name, _QTYPES["A"], server, timeout=TIMEOUT)
    return status == "NOERROR" and bool(records)


def captive_probe(timeout: float = TIMEOUT) -> tuple[str, str]:
    """("open" | "portal" | "error", detail) from Apple's captive-portal URL."""
    conn = http.client.HTTPConnection(CAPTIVE_HOST, 80, timeout=timeout)
    try:
        conn.request("GET", CAPTIVE_PATH, headers={"User-Agent": "xping/doctor"})
        resp = conn.getresponse()
        body = resp.read(2048)
    except (OSError, http.client.HTTPException) as exc:
        return "error", str(exc) or type(exc).__name__
    finally:
        conn.close()
    if resp.status == 200 and b"Success" in body:
        return "open", "no login page"
    location = resp.getheader("Location")
    if location:
        return "portal", f"HTTP {resp.status} redirect to {location}"
    return "portal", f"HTTP {resp.status} with unexpected content"


def https_probe(timeout: float = TIMEOUT + 2) -> tuple[str, str, float | None]:
    """("ok" | "cert" | "error", detail, server unix time or None)."""
    req = urllib.request.Request(TRACE_URL, headers={"User-Agent": "xping/doctor"})
    try:
        with urllib.request.urlopen(req, context=secure_context(), timeout=timeout) as resp:
            fields = net_diag.parse_cf_trace(resp.read(4096).decode("utf-8", "replace"))
    except ssl.SSLCertVerificationError as exc:
        return "cert", exc.verify_message or str(exc), None
    except Exception as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLCertVerificationError):
            return "cert", reason.verify_message or str(reason), None
        return "error", str(reason) or type(reason).__name__, None
    try:
        server_ts = float(fields.get("ts", ""))
    except ValueError:
        server_ts = None
    return "ok", f"TLS {fields.get('tls', '').replace('TLSv', '') or 'ok'}", server_ts


# ── steps ─────────────────────────────────────────────────────────────────────


def _global(address: str | None) -> bool:
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return not (ip.is_link_local or ip.is_loopback or ip.is_unspecified)


def _ms(values: list[float]) -> float | None:
    ok = [v for v in values if v >= 0]
    return sum(ok) / len(ok) if ok else None


def _interface_step(info: NetResult) -> DoctorStep:
    step = DoctorStep("interface", "Network interface", OK)
    v4 = info.local_ipv4
    if v4 and v4.startswith("169.254."):
        step.status = FAIL
        step.detail = f"self-assigned address {v4} — no address from the router (DHCP)"
        step.hint = "Restart the router, or disconnect and reconnect to renew the DHCP lease."
        return step
    if not _global(v4) and not _global(info.local_ipv6):
        step.status = FAIL
        step.detail = "no interface has a usable IP address"
        step.hint = "Connect to Wi-Fi or plug in the cable, and check airplane mode / VPN apps."
        return step
    iface = info.gateway_interface or next(
        (i.name for i in info.interfaces if v4 and any(a.split("/")[0] == v4 for a in i.addresses)),
        None,
    )
    step.detail = " ".join(p for p in (iface, v4 or info.local_ipv6) if p)
    return step


def _gateway_step(info: NetResult) -> DoctorStep:
    step = DoctorStep("gateway", "Default gateway", OK)
    gateway = info.gateway_ipv4 or info.gateway_ipv6
    if not gateway:
        step.status = FAIL
        step.detail = "no default route"
        step.hint = "The network gave you an address but no router — reconnect, or check VPN/static IP settings."
        return step
    started = time.perf_counter()
    rtts = ping_ip(gateway)
    step.elapsed_ms = (time.perf_counter() - started) * 1000
    avg = _ms(rtts)
    if avg is None:
        step.status = WARN
        step.detail = f"{gateway} does not answer ping"
        step.hint = "Some routers ignore ping; this only matters if the internet test fails too."
    else:
        step.detail = f"{gateway} replied in {avg:.1f} ms"
    return step


def _internet_step() -> tuple[DoctorStep, dict[str, float | None]]:
    step = DoctorStep("internet", "Internet (by IP)", OK)
    with ThreadPoolExecutor(max_workers=len(ANYCAST_V4)) as pool:
        times = dict(zip(ANYCAST_V4, pool.map(tcp_connect, ANYCAST_V4), strict=True))
    reached = {ip: ms for ip, ms in times.items() if ms is not None}
    if not reached:
        step.status = FAIL
        step.detail = "no connection to " + ", ".join(ANYCAST_V4) + " (TCP 443)"
        return step, times
    best = min(reached, key=reached.__getitem__)
    step.detail = f"reached {len(reached)}/{len(times)} — {best} in {reached[best]:.1f} ms"
    step.elapsed_ms = reached[best]
    return step, times


def _dns_step(info: NetResult) -> DoctorStep:
    step = DoctorStep("dns", "DNS", OK)
    servers = ", ".join(info.dns_servers[:3]) or "system resolver"
    for name in PROBE_NAMES:
        address, elapsed = system_resolve(name)
        if address:
            step.detail = f"{name} → {address} in {elapsed:.0f} ms via {servers}"
            step.elapsed_ms = elapsed
            if elapsed > 1000:
                step.status = WARN
                step.hint = "Name lookups are slow; a faster DNS server (e.g. 1.1.1.1) may help."
            return step
    step.status = FAIL
    if direct_dns(PROBE_NAMES[0]):
        step.detail = f"your DNS servers ({servers}) do not answer, but public DNS does"
        step.hint = (
            "Switch DNS to 1.1.1.1 or 8.8.8.8 (or restart the router, which usually provides DNS)."
        )
    else:
        step.detail = f"no answer from your DNS servers ({servers}) or from 1.1.1.1"
        step.hint = "DNS traffic seems blocked; check the firewall/VPN, or use DNS-over-HTTPS."
    return step


def _quality_step() -> DoctorStep:
    step = DoctorStep("quality", "Connection quality", OK)
    rtts = ping_ip(ANYCAST_V4[0], count=5, timeout=1.5)
    avg = _ms(rtts)
    lost = sum(1 for r in rtts if r < 0)
    loss = lost / len(rtts) * 100
    if avg is None:
        step.status = SKIP
        step.detail = f"{ANYCAST_V4[0]} does not answer ping here"
        return step
    step.detail = f"{loss:.0f}% loss, {avg:.1f} ms average to {ANYCAST_V4[0]}"
    step.elapsed_ms = avg
    if loss >= 20 or avg > 300:
        step.status = WARN
        step.hint = "The connection is unstable or slow; weak Wi-Fi signal or a busy link are common causes."
    return step


def _captive_step() -> DoctorStep:
    step = DoctorStep("captive", "Captive portal", OK)
    state, detail = captive_probe()
    if state == "open":
        step.detail = detail
    elif state == "portal":
        step.status = FAIL
        step.detail = detail
        step.hint = "Open any web page in a browser and sign in to the Wi-Fi network."
    else:
        step.status = SKIP
        step.detail = f"{CAPTIVE_HOST} unreachable ({detail})"
    return step


def _https_step(now: float) -> DoctorStep:
    step = DoctorStep("https", "HTTPS", OK)
    state, detail, server_ts = https_probe()
    if state == "cert":
        step.status = FAIL
        step.detail = f"certificate check failed: {detail}"
        step.hint = (
            "HTTPS is being intercepted (proxy, antivirus, firewall) or the system clock is wrong."
        )
        return step
    if state == "error":
        step.status = WARN
        step.detail = f"www.cloudflare.com: {detail}"
        step.hint = (
            "Plain connections work but HTTPS to this site failed; a filter may be blocking it."
        )
        return step
    step.detail = detail
    if server_ts is not None:
        skew = now - server_ts
        if abs(skew) > CLOCK_SKEW_WARN_S:
            step.status = WARN
            direction = "ahead" if skew > 0 else "behind"
            step.detail += f"; system clock is {_duration(abs(skew))} {direction}"
            step.hint = "Turn on automatic date & time; a wrong clock breaks HTTPS and logins."
        else:
            step.detail += f"; clock within {abs(skew):.0f}s"
    return step


def _ipv6_step(info: NetResult) -> DoctorStep:
    step = DoctorStep("ipv6", "IPv6", INFO)
    if not _global(info.local_ipv6):
        step.detail = "no IPv6 address (fine — IPv4 is used)"
        return step
    ms = tcp_connect(ANYCAST_V6)
    if ms is None:
        step.detail = f"address {info.local_ipv6}, but no IPv6 route to the internet"
    else:
        step.status = OK
        step.detail = f"works — {ANYCAST_V6} in {ms:.1f} ms"
    return step


def _target_step(target: str, port: int) -> DoctorStep:
    step = DoctorStep("target", f"Target {target}", OK)
    address, elapsed = system_resolve(target)
    if not address:
        step.status = FAIL
        step.detail = f"cannot resolve {target}"
        step.hint = "Check the spelling; if the name is right, its DNS is broken or it was removed."
        return step
    ms = tcp_connect(address, port)
    if ms is None:
        step.status = FAIL
        step.detail = f"{address} does not accept connections on port {port}"
        step.hint = f"Your internet works — {target} itself is down, or blocks you/this port."
        return step
    step.detail = f"{address}:{port} connected in {ms:.1f} ms (DNS {elapsed:.0f} ms)"
    step.elapsed_ms = ms
    return step


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.0f} days"


def _skipped(key: str, name: str, why: str) -> DoctorStep:
    return DoctorStep(key, name, SKIP, why)


# ── diagnosis ─────────────────────────────────────────────────────────────────


def diagnose(result: DoctorResult) -> tuple[str, str]:
    """(headline, what to do) from the step statuses — first break wins."""

    def failed(key: str) -> bool:
        step = result.step(key)
        return step is not None and step.status == FAIL

    def hint(key: str) -> str:
        step = result.step(key)
        return step.hint if step else ""

    if failed("interface"):
        step = result.step("interface")
        if step and "DHCP" in step.detail:
            return "Connected, but the router did not give this machine an address.", hint(
                "interface"
            )
        return "This machine is not connected to any network.", hint("interface")
    if failed("gateway"):
        return "There is no router (default route) on this network.", hint("gateway")
    if failed("internet"):
        gateway = result.step("gateway")
        if gateway and gateway.status == WARN:
            return (
                "Neither the router nor the internet responds.",
                "Restart the router; if you are on Wi-Fi, move closer or reconnect.",
            )
        return (
            "The router works, but there is no internet behind it.",
            "Restart the modem/router; if that does not help, the problem is with your ISP.",
        )
    if failed("captive"):
        return "A Wi-Fi login page is blocking internet access.", hint("captive")
    if failed("dns"):
        return "The internet works, but name lookups (DNS) fail.", hint("dns")
    if failed("https"):
        return "Secure (HTTPS) connections are being intercepted or rejected.", hint("https")
    if failed("target"):
        target = result.target or "the target"
        return f"Your internet is fine — the problem is with {target}.", hint("target")
    warnings = [s for s in result.steps if s.status == WARN]
    if warnings:
        names = ", ".join(s.name.lower() for s in warnings)
        return f"The internet works, with warnings: {names}.", warnings[0].hint
    return "Everything looks good — this machine is online.", ""


# ── driver ────────────────────────────────────────────────────────────────────


def doctor(
    target: str | None = None,
    port: int = 443,
    quiet: bool = False,
    clock=time.time,
) -> DoctorResult:
    """Run every step (independent ones in parallel) and diagnose."""
    result = DoctorResult(target=target, port=port if target else None)

    if not quiet:
        title = f"CONNECTIVITY DOCTOR  {target}" if target else "CONNECTIVITY DOCTOR"
        print(section_header(title, "✚"))
        print()

    def show(*steps: DoctorStep) -> None:
        result.steps.extend(steps)
        if not quiet:
            for step in steps:
                doctor_view.print_step(step)

    def phase(label: str, jobs: dict):
        spinner = None
        if not quiet and sys.stdout.isatty():
            spinner = Spinner(c(label, BRAND_TEAL))
            spinner.start()
        try:
            with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
                futures = {key: pool.submit(fn) for key, fn in jobs.items()}
                return {key: f.result() for key, f in futures.items()}
        finally:
            if spinner:
                spinner.stop()

    info = phase("Checking interfaces and routes…", {"info": network_info})["info"]
    interface = _interface_step(info)
    show(interface)

    later = (
        ("gateway", "Default gateway"),
        ("internet", "Internet (by IP)"),
        ("dns", "DNS"),
        ("quality", "Connection quality"),
        ("captive", "Captive portal"),
        ("https", "HTTPS"),
        ("ipv6", "IPv6"),
    )
    if interface.status == FAIL:
        show(*(_skipped(k, n, "no network connection") for k, n in later))
        if target:
            show(_skipped("target", f"Target {target}", "no network connection"))
    else:
        first = phase(
            "Testing router, internet and DNS…",
            {
                "gateway": lambda: _gateway_step(info),
                "internet": _internet_step,
                "dns": lambda: _dns_step(info),
                "ipv6": lambda: _ipv6_step(info),
            },
        )
        internet, _times = first["internet"]
        show(first["gateway"], internet, first["dns"])

        online = internet.status != FAIL
        dns_ok = first["dns"].status != FAIL
        jobs: dict = {}
        if online:
            jobs["quality"] = _quality_step
        if online and dns_ok:
            jobs["captive"] = _captive_step
            jobs["https"] = lambda: _https_step(clock())
            if target:
                jobs["target"] = lambda: _target_step(target, port)
        second = phase("Checking connection quality, login pages and HTTPS…", jobs) if jobs else {}

        why = "no internet connection" if not online else "DNS is not working"
        show(second.get("quality") or _skipped("quality", "Connection quality", why))
        show(second.get("captive") or _skipped("captive", "Captive portal", why))
        show(second.get("https") or _skipped("https", "HTTPS", why))
        show(first["ipv6"])
        if target:
            show(second.get("target") or _skipped("target", f"Target {target}", why))

    result.diagnosis, result.hint = diagnose(result)
    if not quiet:
        doctor_view.print_diagnosis(result)
    return result
