"""Wi-Fi link render view (xping wifi)."""

from xping.models.wifi import overlaps

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from ..layout import kv
from ..tables import print_table

_QUALITY = {
    "Excellent": BRAND_MINT,
    "Good": BRAND_MINT,
    "Fair": BRAND_AMBER,
    "Weak": BRAND_ROSE,
    "Very weak": BRAND_ROSE,
}


def signal_bar(dbm: int, width: int = 20) -> str:
    """-90 dBm (empty) … -30 dBm (full)."""
    filled = max(0, min(width, round((dbm + 90) / 60 * width)))
    return "█" * filled + "░" * (width - filled)


def _signal(dbm, quality) -> str:
    if dbm is None:
        return c("—", DIM)
    color = _QUALITY.get(quality, BWHITE)
    return (
        c(signal_bar(dbm), color) + "  " + c(f"{dbm} dBm", color, BOLD) + c(f"  {quality}", color)
    )


def _channel(net) -> str:
    if net.channel is None:
        return c("—", DIM)
    parts = [str(net.channel)]
    if net.band:
        parts.append(net.band)
    if net.width_mhz:
        parts.append(f"{net.width_mhz} MHz wide")
    return c(" · ".join(parts), BWHITE)


def print_result(result, tips: list[str], show_nearby: bool = False) -> None:
    if result.error:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
        print()
        return
    net = result.current
    print(kv("Interface", c(result.interface or "—", BWHITE)))
    if net.ssid:
        print(kv("Network", c(net.ssid, BWHITE, BOLD)))
    else:
        print(kv("Network", c("name hidden by the OS (macOS needs Location Services for it)", DIM)))
    print(kv("Signal", _signal(net.signal_dbm, result.quality)))
    if net.noise_dbm is not None:
        snr = net.snr_db
        snr_color = BRAND_MINT if snr >= 25 else BRAND_AMBER if snr >= 15 else BRAND_ROSE
        print(
            kv(
                "Noise",
                c(f"{net.noise_dbm} dBm", BWHITE)
                + c("   SNR ", DIM)
                + c(f"{snr} dB", snr_color, BOLD),
            )
        )
    print(kv("Channel", _channel(net)))
    if result.tx_rate_mbps:
        rate = f"{result.tx_rate_mbps:g} Mbit/s" + (
            f"  (MCS {result.mcs})" if result.mcs is not None else ""
        )
        print(kv("Link rate", c(rate, BWHITE)))
    if net.phy_mode:
        print(kv("Standard", c(net.phy_mode, BWHITE)))
    if net.security:
        weak = net.security in ("Open", "WEP") or net.security.upper().startswith("WPA ")
        print(kv("Security", c(net.security, BRAND_ROSE if weak else BWHITE)))
    if result.nearby:
        shared = result.same_channel
        text = f"{len(result.nearby)} networks, {shared} on your channel"
        print(kv("Nearby", c(text, BRAND_AMBER if shared >= 3 else BWHITE)))
    print()
    if show_nearby and result.nearby:
        rows = []
        for other in sorted(result.nearby, key=lambda n: n.signal_dbm or -200, reverse=True):
            mark = c(" ◀ same channel", BRAND_AMBER) if overlaps(net, other) else ""
            rows.append(
                [
                    c(other.ssid or "(hidden)", BWHITE if other.ssid else DIM),
                    f"{other.channel or '—'}",
                    other.band or "—",
                    f"{other.signal_dbm} dBm" if other.signal_dbm is not None else "—",
                    (other.security or "—") + mark,
                ]
            )
        print_table(["Network", "Channel", "Band", "Signal", "Security"], rows)
        print()
    for tip in tips:
        print(c(f"  → {tip}", BRAND_SLATE))
    if tips:
        print()
