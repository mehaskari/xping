"""xping wifi — OS output parsers, advice and verdicts (no real Wi-Fi needed)."""

import json
from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.cli.verdict import evaluate
from xping.diagnostics import wifi as wd
from xping.exporters.json import export_json
from xping.models.wifi import WifiNetwork, WifiResult, overlaps

PROFILER = json.dumps({"SPAirPortDataType": [{"spairport_airport_interfaces": [
    {
        "_name": "en0",
        "spairport_wireless_card_type": "spairport_wireless_card_type_wifi (0x14E4, 0x4387)",
        "spairport_wireless_country_code": "GB",
        "spairport_status_information": "spairport_status_connected",
        "spairport_current_network_information": {
            "_name": "<redacted>",
            "spairport_network_channel": "132 (5GHz, 40MHz)",
            "spairport_network_mcs": 9,
            "spairport_network_phymode": "802.11ac",
            "spairport_network_rate": 400,
            "spairport_security_mode": "spairport_security_mode_wpa3_personal",
            "spairport_signal_noise": "-44 dBm / -94 dBm",
        },
        "spairport_airport_other_local_wireless_networks": [
            {"_name": "Neighbour", "spairport_network_channel": "6 (2GHz, 20MHz)",
             "spairport_security_mode": "spairport_security_mode_wpa2_personal_mixed",
             "spairport_signal_noise": "-70 dBm / -95 dBm"},
        ],
    },
    {"_name": "awdl0", "spairport_current_network_information": {}},
]}]})

IW_LINK = """Connected to 11:22:33:44:55:66 (on wlan0)
\tSSID: HomeNet
\tfreq: 2437
\tRX: 1234 bytes (10 packets)
\tsignal: -71 dBm
\trx bitrate: 65.0 MBit/s
\ttx bitrate: 72.2 MBit/s MCS 7 20MHz short GI
"""
PROC_WIRELESS = """Inter-| sta-|   Quality        |   Discarded packets
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
wlan0: 0000   39.  -71.  -92.       0      0      0      0      0        0
"""
NMCLI = r"""*:HomeNet:11\:22\:33\:44\:55\:66:6:2437 MHz:58:WPA2
:Café\:Guest:AA\:BB\:CC\:DD\:EE\:FF:6:2437 MHz:40:
:Other:AA\:BB\:CC\:DD\:EE\:01:44:5220 MHz:80:WPA2 WPA3
"""
NETSH_IF = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    Physical address       : aa:bb:cc:dd:ee:ff
    State                  : connected
    SSID                   : HomeNet
    BSSID                  : 11:22:33:44:55:66
    Network type           : Infrastructure
    Radio type             : 802.11ax
    Authentication         : WPA2-Personal
    Band                   : 5 GHz
    Channel                : 36
    Receive rate (Mbps)    : 1201
    Transmit rate (Mbps)   : 960
    Signal                 : 92%
"""
NETSH_NETS = """
SSID 1 : HomeNet
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    BSSID 1                 : 11:22:33:44:55:66
         Signal             : 92%
         Band               : 5 GHz
         Channel            : 36
SSID 2 : Neighbour
    Authentication          : Open
    BSSID 1                 : 66:55:44:33:22:11
         Signal             : 40%
         Channel            : 36
"""


def test_helpers():
    assert wd.channel_from_freq(2437) == (6, "2.4 GHz")
    assert wd.channel_from_freq(5180) == (36, "5 GHz") and wd.channel_from_freq(5955)[1] == "6 GHz"
    assert wd.pct_to_dbm(100) == -50 and wd.pct_to_dbm(0) == -100
    assert overlaps(WifiNetwork(channel=1, band="2.4 GHz"), WifiNetwork(channel=4, band="2.4 GHz"))
    assert not overlaps(WifiNetwork(channel=1, band="2.4 GHz"), WifiNetwork(channel=6, band="2.4 GHz"))
    assert not overlaps(WifiNetwork(channel=36, band="5 GHz"), WifiNetwork(channel=40, band="5 GHz"))


def test_macos_system_profiler():
    (result,) = wd.parse_system_profiler(PROFILER)  # awdl0 skipped
    net = result.current
    assert result.connected and result.interface == "en0" and result.tx_rate_mbps == 400
    assert net.ssid is None and (net.channel, net.band, net.width_mhz) == (132, "5 GHz", 40)
    assert (net.signal_dbm, net.noise_dbm, net.snr_db) == (-44, -94, 50)
    assert net.security == "WPA3 Personal" and result.quality == "Excellent"
    assert result.nearby[0].security == "WPA2 Personal (mixed)" and result.nearby[0].ssid == "Neighbour"


def test_linux_iw_proc_and_nmcli():
    result = wd.parse_iw_link(IW_LINK)
    net = result.current
    assert (net.ssid, net.bssid, net.channel, net.band) == ("HomeNet", "11:22:33:44:55:66", 6, "2.4 GHz")
    assert net.signal_dbm == -71 and result.tx_rate_mbps == 72.2 and result.mcs == 7 and net.width_mhz == 20
    assert wd.parse_iw_link("Not connected.") is None
    assert wd.parse_proc_wireless(PROC_WIRELESS, "wlan0") == -92
    nets = wd.parse_nmcli(NMCLI)
    assert nets[0][0] and nets[0][1].bssid == "11:22:33:44:55:66" and nets[0][1].signal_dbm == -71
    assert nets[1][1].ssid == "Café:Guest" and nets[1][1].security == "Open"
    assert nets[2][1].band == "5 GHz"
    assert wd.parse_iw_dev("phy#0\n\tInterface wlan0\n\t\tifindex 3\n") == ["wlan0"]


def test_windows_netsh():
    (result,) = wd.parse_netsh_interfaces(NETSH_IF)
    net = result.current
    assert result.connected and (net.ssid, net.channel, net.band) == ("HomeNet", 36, "5 GHz")
    assert net.signal_dbm == -54 and result.tx_rate_mbps == 960 and net.security == "WPA2-Personal"
    nearby = wd.parse_netsh_networks(NETSH_NETS)
    assert [n.ssid for n in nearby] == ["HomeNet", "Neighbour"] and nearby[1].band == "5 GHz"
    assert nearby[1].security == "Open" and nearby[1].signal_dbm == -80
    disconnected = wd.parse_netsh_interfaces(NETSH_IF.replace(": connected", ": disconnected"))
    assert disconnected[0].current is None


def _crowded(channel=6, signal=-72):
    me = WifiNetwork(channel=channel, band="2.4 GHz", signal_dbm=signal, noise_dbm=-90)
    nearby = [WifiNetwork(channel=c, band="2.4 GHz") for c in (5, 6, 7, 11)]
    return WifiResult(connected=True, current=me, nearby=nearby)


def test_advice():
    tips = wd.advice(_crowded())
    assert any("weak for calls" in t for t in tips)
    assert any("SNR" in t or "Signal-to-noise" in t for t in tips)
    assert any("3 nearby networks share your 2.4 GHz channel" in t and "channel 1" in t for t in tips)
    strong = WifiResult(connected=True, current=WifiNetwork(channel=1, band="2.4 GHz", signal_dbm=-45))
    assert any("5 GHz would likely be much faster" in t for t in wd.advice(strong))
    assert wd.best_24ghz_channel(_crowded()) == 1


def test_wifi_picks_connected_interface_and_errors():
    idle = WifiResult(interface="wlan1", source="iw")
    up = wd.parse_iw_link(IW_LINK)
    up.interface = "wlan0"
    with patch.object(wd.sys, "platform", "linux"), patch.object(wd, "_linux", return_value=[idle, up]):
        assert wd.wifi(quiet=True).interface == "wlan0"
        assert "not connected" in wd.wifi(interface="wlan1", quiet=True).error
    with patch.object(wd.sys, "platform", "linux"), patch.object(wd, "_linux", return_value=[]):
        result = wd.wifi(quiet=True)
    assert result.error == "no Wi-Fi interface found" and evaluate(result)


def test_verdict_and_exports():
    result = wd.parse_system_profiler(PROFILER)[0]
    assert evaluate(result) == []
    assert evaluate(result, type("O", (), {"min_signal": -40})())[0].threshold
    data = json.loads(export_json(result))
    assert data["quality"] == "Excellent" and data["current"]["snr_db"] == 50


def test_render(capsys):
    from xping.render.views import wifi as view

    result = wd.parse_system_profiler(PROFILER)[0]
    with patch("xping.render.COLOR", False), patch("xping.render.ansi.COLOR", False):
        view.print_result(result, [], show_nearby=True)
    out = capsys.readouterr().out
    assert "-44 dBm  Excellent" in out and "SNR 50 dB" in out and "hidden by the OS" in out
    assert "Neighbour" in out and "1 networks, 0 on your channel" in out


@pytest.mark.parametrize("argv", [["wifi"], ["wifi", "-i", "en0", "--nearby", "--min-signal", "-67"]])
def test_parser(argv):
    args = build_parser().parse_args(argv)
    assert args.command == "wifi"
