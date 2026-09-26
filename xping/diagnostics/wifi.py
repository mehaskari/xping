"""
xping.diagnostics.wifi — how good is this Wi-Fi link?

Signal and noise (dBm), signal-to-noise ratio, channel and band, link
rate, security, and how many nearby networks share the channel — the
usual reasons Wi-Fi is slow. Read from the OS's own tools, no root:

  macOS    system_profiler SPAirPortDataType -json
           (macOS hides network names from apps without Location
           Services permission; everything else is available)
  Linux    iw dev / iw dev IFACE link, nmcli for nearby networks
  Windows  netsh wlan show interfaces / networks mode=bssid
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

from xping.models.wifi import WifiNetwork, WifiResult, overlaps
from xping.render import BRAND_TEAL, c, section_header
from xping.render.animations import Spinner
from xping.render.views import wifi as wifi_view

_CHANNELS_24 = (1, 6, 11)  # the only non-overlapping 2.4 GHz channels


def _run(*cmd: str, timeout: float = 15) -> str | None:
    try:
        proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


# ── helpers ───────────────────────────────────────────────────────────────────


def channel_from_freq(mhz: int) -> tuple[int | None, str | None]:
    """(channel, band) for a centre frequency in MHz."""
    if 2412 <= mhz <= 2472:
        return (mhz - 2407) // 5, "2.4 GHz"
    if mhz == 2484:
        return 14, "2.4 GHz"
    if 5150 <= mhz <= 5895:
        return (mhz - 5000) // 5, "5 GHz"
    if 5925 <= mhz <= 7125:
        return (mhz - 5950) // 5, "6 GHz"
    return None, None


def band_of_channel(channel: int) -> str:
    return "2.4 GHz" if channel <= 14 else "5 GHz"


def pct_to_dbm(pct: int) -> int:
    """Windows / NetworkManager report signal as 0-100 %; the usual mapping
    is linear between -100 dBm (0 %) and -50 dBm (100 %)."""
    return round(pct / 2 - 100)


def _int(value: str | None) -> int | None:
    m = re.search(r"-?\d+", value or "")
    return int(m.group()) if m else None


def _float(value: str | None) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", value or "")
    return float(m.group()) if m else None


# ── macOS ─────────────────────────────────────────────────────────────────────

_SECURITY = {
    "wpa3_personal": "WPA3 Personal",
    "wpa2_personal": "WPA2 Personal",
    "wpa2_wpa3_personal": "WPA2/WPA3 Personal",
    "wpa_wpa2_personal": "WPA/WPA2 Personal",
    "wpa2_enterprise": "WPA2 Enterprise",
    "wpa3_enterprise": "WPA3 Enterprise",
    "none": "Open",
    "wep": "WEP",
}


def _security_words(raw: str) -> str | None:
    """ "wpa2_personal_mixed" -> "WPA2 Personal (mixed)"."""
    words = [w for w in raw.split("_") if w]
    if not words:
        return None
    named = [w.upper() if w.startswith(("wpa", "wep")) else w.capitalize() for w in words]
    if named[-1] in ("Mixed", "Transition"):
        return " ".join(named[:-1]) + f" ({named[-1].lower()})"
    return " ".join(named)


def _mac_network(info: dict) -> WifiNetwork:
    net = WifiNetwork()
    name = info.get("_name")
    net.ssid = None if not name or name == "<redacted>" else name
    m = re.match(
        r"(\d+)\s*\((\d+(?:\.\d+)?)GHz(?:,\s*(\d+)MHz)?\)",
        info.get("spairport_network_channel", ""),
    )
    if m:
        net.channel = int(m.group(1))
        net.band = "2.4 GHz" if m.group(2).startswith("2") else f"{m.group(2)} GHz"
        net.width_mhz = int(m.group(3)) if m.group(3) else None
    sn = re.match(r"(-?\d+)\s*dBm\s*/\s*(-?\d+)\s*dBm", info.get("spairport_signal_noise", ""))
    if sn:
        net.signal_dbm, net.noise_dbm = int(sn.group(1)), int(sn.group(2))
    security = info.get("spairport_security_mode", "").replace("spairport_security_mode_", "")
    net.security = _SECURITY.get(security) or _security_words(security)
    net.phy_mode = info.get("spairport_network_phymode")
    return net


def parse_system_profiler(text: str) -> list[WifiResult]:
    """One result per Wi-Fi interface in `system_profiler -json SPAirPortDataType`."""
    results = []
    for item in json.loads(text).get("SPAirPortDataType", []):
        for iface in item.get("spairport_airport_interfaces", []):
            if "spairport_wireless_card_type" not in iface:
                continue  # awdl0 & co. are not Wi-Fi links
            result = WifiResult(interface=iface.get("_name"), source="system_profiler")
            result.country = iface.get("spairport_wireless_country_code")
            result.connected = iface.get("spairport_status_information", "").endswith("connected")
            current = iface.get("spairport_current_network_information")
            if result.connected and current:
                result.current = _mac_network(current)
                result.tx_rate_mbps = _float(str(current.get("spairport_network_rate", "")))
                result.mcs = current.get("spairport_network_mcs")
            result.nearby = [
                _mac_network(n)
                for n in iface.get("spairport_airport_other_local_wireless_networks", [])
            ]
            results.append(result)
    return results


def _darwin() -> list[WifiResult]:
    text = _run("system_profiler", "-json", "SPAirPortDataType", timeout=30)
    return parse_system_profiler(text) if text else []


# ── Linux ─────────────────────────────────────────────────────────────────────


def parse_iw_dev(text: str) -> list[str]:
    return re.findall(r"^\s*Interface\s+(\S+)", text, re.M)


def parse_iw_link(text: str) -> WifiResult | None:
    """`iw dev IFACE link`; None when not connected."""
    if not text or "Not connected" in text:
        return None
    net = WifiNetwork()
    result = WifiResult(connected=True, current=net, source="iw")
    m = re.search(r"Connected to ([0-9a-f:]{17})", text, re.I)
    net.bssid = m.group(1).lower() if m else None
    m = re.search(r"^\s*SSID:\s*(.*)$", text, re.M)
    net.ssid = m.group(1).strip() if m else None
    m = re.search(r"^\s*freq:\s*(\d+)", text, re.M)
    if m:
        net.channel, net.band = channel_from_freq(int(m.group(1)))
    m = re.search(r"^\s*signal:\s*(-?\d+)\s*dBm", text, re.M)
    net.signal_dbm = int(m.group(1)) if m else None
    m = re.search(r"^\s*tx bitrate:\s*([\d.]+)\s*MBit/s(.*)$", text, re.M)
    if m:
        result.tx_rate_mbps = float(m.group(1))
        width = re.search(r"(\d+)MHz", m.group(2))
        net.width_mhz = int(width.group(1)) if width else None
        mcs = re.search(r"MCS (\d+)", m.group(2))
        result.mcs = int(mcs.group(1)) if mcs else None
    return result


def parse_proc_wireless(text: str, iface: str) -> int | None:
    """Noise level (dBm) from /proc/net/wireless, if the driver reports it."""
    for line in text.splitlines():
        parts = line.replace(":", " ").split()
        if parts and parts[0] == iface and len(parts) >= 5:
            noise = _int(parts[4])
            return noise if noise is not None and -110 < noise < 0 else None
    return None


def _nmcli_fields(line: str) -> list[str]:
    """Split a terse nmcli line on unescaped colons."""
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r"(?<!\\):", line)]


def parse_nmcli(text: str) -> list[tuple[bool, WifiNetwork]]:
    """`nmcli -t -f IN-USE,SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY dev wifi list`."""
    networks = []
    for line in text.splitlines():
        fields = _nmcli_fields(line)
        if len(fields) < 7:
            continue
        in_use, ssid, bssid, chan, freq, signal, security = fields[:7]
        channel = _int(chan)
        net = WifiNetwork(
            ssid=ssid or None,
            bssid=bssid.lower() or None,
            channel=channel,
            band=channel_from_freq(_int(freq) or 0)[1]
            or (band_of_channel(channel) if channel else None),
            signal_dbm=pct_to_dbm(_int(signal)) if _int(signal) is not None else None,
            security=security or "Open",
        )
        networks.append((in_use.strip() == "*", net))
    return networks


def _linux() -> list[WifiResult]:
    results = []
    interfaces = parse_iw_dev(_run("iw", "dev") or "") if shutil.which("iw") else []
    nearby: list[tuple[bool, WifiNetwork]] = []
    if shutil.which("nmcli"):
        nearby = parse_nmcli(
            _run(
                "nmcli",
                "-t",
                "-f",
                "IN-USE,SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY",
                "dev",
                "wifi",
                "list",
            )
            or ""
        )
    try:
        with open("/proc/net/wireless", encoding="utf-8") as f:
            proc = f.read()
    except OSError:
        proc = ""
    for iface in interfaces:
        result = parse_iw_link(_run("iw", "dev", iface, "link") or "") or WifiResult(source="iw")
        result.interface = iface
        if result.current:
            result.current.noise_dbm = parse_proc_wireless(proc, iface)
            active = next((n for used, n in nearby if used), None)
            if active and not result.current.security:
                result.current.security = active.security
        result.nearby = [n for used, n in nearby if not used]
        results.append(result)
    if not results and nearby:  # no iw: NetworkManager alone
        active = next((n for used, n in nearby if used), None)
        results.append(
            WifiResult(
                connected=active is not None,
                current=active,
                nearby=[n for used, n in nearby if not used],
                source="nmcli",
            )
        )
    return results


# ── Windows ───────────────────────────────────────────────────────────────────


def _kv_lines(text: str):
    for line in text.splitlines():
        m = re.match(r"^\s*([^:]+?)\s*:\s*(.*)$", line)
        if m:
            yield m.group(1).strip().lower(), m.group(2).strip(), line


def parse_netsh_interfaces(text: str) -> list[WifiResult]:
    results: list[WifiResult] = []
    current: WifiResult | None = None
    for key, value, _line in _kv_lines(text):
        if key == "name":
            current = WifiResult(interface=value, source="netsh")
            results.append(current)
            continue
        if current is None:
            continue
        net = current.current or WifiNetwork()
        if key == "state":
            current.connected = value.lower() == "connected"
        elif key == "ssid":
            net.ssid = value or None
        elif key == "bssid":
            net.bssid = value.lower()
        elif key == "radio type":
            net.phy_mode = value
        elif key == "authentication":
            net.security = value
        elif key == "band":
            net.band = "2.4 GHz" if value.startswith("2.4") else value
        elif key == "channel":
            net.channel = _int(value)
        elif key.startswith("transmit rate"):
            current.tx_rate_mbps = _float(value)
        elif key == "signal":
            pct = _int(value)
            net.signal_dbm = pct_to_dbm(pct) if pct is not None else None
        else:
            continue
        current.current = net
    for result in results:
        if not result.connected:
            result.current = None
        elif result.current and result.current.channel and not result.current.band:
            result.current.band = band_of_channel(result.current.channel)
    return results


def parse_netsh_networks(text: str) -> list[WifiNetwork]:
    networks: list[WifiNetwork] = []
    ssid, security, net = None, None, None
    for key, value, _line in _kv_lines(text):
        if re.match(r"ssid \d+", key):
            ssid, security = value or None, None
        elif key == "authentication":
            security = value
        elif re.match(r"bssid \d+", key):
            net = WifiNetwork(ssid=ssid, bssid=value.lower(), security=security)
            networks.append(net)
        elif net is None:
            continue
        elif key == "signal":
            pct = _int(value)
            net.signal_dbm = pct_to_dbm(pct) if pct is not None else None
        elif key == "radio type":
            net.phy_mode = value
        elif key == "band":
            net.band = "2.4 GHz" if value.startswith("2.4") else value
        elif key == "channel":
            net.channel = _int(value)
            net.band = net.band or band_of_channel(net.channel or 0)
    return networks


def _windows() -> list[WifiResult]:
    results = parse_netsh_interfaces(_run("netsh", "wlan", "show", "interfaces") or "")
    nearby = parse_netsh_networks(_run("netsh", "wlan", "show", "networks", "mode=bssid") or "")
    for result in results:
        mine = result.current.bssid if result.current else None
        result.nearby = [n for n in nearby if n.bssid != mine]
    return results


# ── advice ────────────────────────────────────────────────────────────────────


def best_24ghz_channel(result: WifiResult) -> int | None:
    """The least crowded of channels 1 / 6 / 11 among nearby networks."""
    probe = WifiNetwork(band="2.4 GHz")
    counts = {}
    for channel in _CHANNELS_24:
        probe.channel = channel
        counts[channel] = sum(1 for n in result.nearby if overlaps(probe, n))
    return min(counts, key=lambda ch: (counts[ch], ch)) if counts else None


def advice(result: WifiResult) -> list[str]:
    tips: list[str] = []
    net = result.current
    if not net:
        return tips
    if net.signal_dbm is not None and net.signal_dbm < -67:
        tips.append(
            "Signal is weak for calls and streaming (below -67 dBm): move closer to the router,"
            " or add an access point / mesh node."
        )
    snr = net.snr_db
    if snr is not None and snr < 25:
        tips.append(
            f"Signal-to-noise ratio is low ({snr} dB): interference from other networks or devices"
            " (microwaves, Bluetooth) is costing speed."
        )
    if result.same_channel >= 3:
        if net.band == "2.4 GHz":
            best = best_24ghz_channel(result)
            better = f" (least used nearby: channel {best})" if best and best != net.channel else ""
            tips.append(
                f"{result.same_channel} nearby networks share your 2.4 GHz channel: switch to 5 GHz,"
                f" or change the router's channel{better}."
            )
        else:
            tips.append(
                f"{result.same_channel} nearby networks use the same channel: pick another channel"
                " in the router settings."
            )
    elif net.band == "2.4 GHz" and net.signal_dbm is not None and net.signal_dbm >= -60:
        tips.append("You are on 2.4 GHz with a strong signal — 5 GHz would likely be much faster.")
    return tips


# ── driver ────────────────────────────────────────────────────────────────────


def wifi(
    interface: str | None = None, quiet: bool = False, show_nearby: bool = False
) -> WifiResult:
    if not quiet:
        print(section_header("WI-FI", "≋"))
        print()
    spinner = None
    if not quiet and sys.stdout.isatty():
        spinner = Spinner(c("Reading Wi-Fi status…", BRAND_TEAL))
        spinner.start()
    try:
        if sys.platform == "darwin":
            results = _darwin()
        elif sys.platform == "win32":
            results = _windows()
        else:
            results = _linux()
    finally:
        if spinner:
            spinner.stop()

    if interface:
        results = [r for r in results if r.interface == interface]
    connected = [r for r in results if r.connected]
    if connected:
        result = connected[0]
    elif results:
        result = results[0]
        result.error = f"Wi-Fi interface {result.interface or ''} is not connected".replace(
            "  ", " "
        )
    else:
        where = f" named {interface}" if interface else ""
        result = WifiResult(interface=interface, error=f"no Wi-Fi interface{where} found")
    if not quiet:
        wifi_view.print_result(result, advice(result), show_nearby=show_nearby)
    return result
