"""xping lan — ARP tables, vendors, network choice and the flow (network faked)."""

import ipaddress
from unittest.mock import patch

import pytest

from xping.cli.parser import build_parser
from xping.diagnostics import lan as lan_mod
from xping.exporters.csv import export_csv
from xping.models.lan import LanResult
from xping.models.net import NetInterface, NetResult
from xping.verdict import evaluate

ARP_AN = """\
? (192.168.1.1) at e0:a4:98:5:e:68 on en0 ifscope [ethernet]
? (192.168.1.103) at c2:6:c3:4:98:ee on en0 ifscope [ethernet]
? (192.168.1.50) at (incomplete) on en0 ifscope [ethernet]
? (224.0.0.251) at 1:0:5e:0:0:fb on en0 ifscope permanent [ethernet]
? (192.168.1.255) at ff:ff:ff:ff:ff:ff on en0 ifscope [ethernet]
"""

PROC_ARP = """\
IP address       HW type     Flags       HW address            Mask     Device
192.168.1.1      0x1         0x2         e0:a4:98:05:0e:68     *        wlan0
192.168.1.77     0x1         0x0         00:00:00:00:00:00     *        wlan0
10.0.0.9         0x1         0x2         b8:27:eb:12:34:56     *        eth1
"""

ARP_WINDOWS = """\
Interface: 192.168.1.5 --- 0x7
  Internet Address      Physical Address      Type
  192.168.1.1           e0-a4-98-05-0e-68     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
"""


def test_normalize_and_classify_macs():
    assert lan_mod.normalize_mac("e0:a4:98:5:e:68") == "e0:a4:98:05:0e:68"
    assert lan_mod.normalize_mac("E0-A4-98-05-0E-68") == "e0:a4:98:05:0e:68"
    assert lan_mod.normalize_mac("(incomplete)") is None
    assert lan_mod.is_random_mac("c2:06:c3:04:98:ee") and not lan_mod.is_random_mac("e0:a4:98:05:0e:68")
    assert lan_mod._unusable("ff:ff:ff:ff:ff:ff") and lan_mod._unusable("01:00:5e:00:00:fb")


def test_arp_parsers():
    assert lan_mod.parse_arp_an(ARP_AN) == {
        "192.168.1.1": "e0:a4:98:05:0e:68",
        "192.168.1.103": "c2:06:c3:04:98:ee",
        "224.0.0.251": "01:00:5e:00:00:fb",
        "192.168.1.255": "ff:ff:ff:ff:ff:ff",
    }
    assert lan_mod.parse_proc_arp(PROC_ARP) == {
        "192.168.1.1": "e0:a4:98:05:0e:68",
        "10.0.0.9": "b8:27:eb:12:34:56",
    }
    assert lan_mod.parse_arp_windows(ARP_WINDOWS)["192.168.1.1"] == "e0:a4:98:05:0e:68"


def test_vendor_databases_in_every_format():
    nmap = "# comment\nB827EB Raspberry Pi Foundation\n"
    manuf = "B8:27:EB\tRaspberr\tRaspberry Pi Foundation\n00:1B:C5:00:00/36\tX\tSkip\nAA:BB:CC\tShort\n"
    ieee = "B8-27-EB   (hex)\t\tRaspberry Pi Foundation\nB827EB     (base 16)\t\tRaspberry Pi Foundation\n"
    for text in (nmap, manuf, ieee):
        assert lan_mod.parse_vendor_db(text)["b827eb"] == "Raspberry Pi Foundation"
    assert lan_mod.parse_vendor_db(manuf)["aabbcc"] == "Short"
    assert "001bc5" not in lan_mod.parse_vendor_db(manuf)


def test_load_vendors_uses_the_first_database_found(tmp_path):
    db = tmp_path / "nmap-mac-prefixes"
    db.write_text("B827EB Raspberry Pi Foundation\n", encoding="utf-8")
    vendors, path = lan_mod.load_vendors([str(tmp_path / "missing"), str(db)])
    assert vendors == {"b827eb": "Raspberry Pi Foundation"} and path == str(db)
    assert lan_mod.load_vendors([str(tmp_path / "missing")]) == ({}, None)


def _net(gateway="192.168.1.1", vpn=False):
    ifaces = [
        NetInterface("lo0", "up", addresses=["127.0.0.1/8"]),
        NetInterface("en0", "up", mac="1a:22:d9:a3:5d:3d", addresses=["192.168.1.111/24"]),
        NetInterface("bridge100", "up", addresses=["192.168.64.1/24"]),
    ]
    if vpn:
        ifaces.append(NetInterface("utun8", "up", addresses=["198.18.0.1/16"]))
    return NetResult(hostname="h", gateway_ipv4=None if vpn else gateway, interfaces=ifaces,
                     vpn_interfaces=["utun8"] if vpn else [])


def test_local_network_prefers_the_gateway_interface():
    with patch.object(lan_mod.net_diag, "net", return_value=_net()):
        addr, iface, gateway, mac = lan_mod.local_network()
    assert (str(addr), iface, gateway, mac) == ("192.168.1.111/24", "en0", "192.168.1.1", "1a:22:d9:a3:5d:3d")


def test_local_network_under_a_full_tunnel_vpn():
    with (
        patch.object(lan_mod.net_diag, "net", return_value=_net(vpn=True)),
        patch.object(lan_mod, "_scoped_gateway", return_value="192.168.1.1"),
    ):
        addr, iface, gateway, _ = lan_mod.local_network()
    assert iface == "en0" and gateway == "192.168.1.1"


def test_device_name_asks_mdns_then_the_router():
    calls = []

    def fake(ip, server, port=53, timeout=0):
        calls.append((server, port))
        return {5353: None, 53: "printer.lan"}[port]

    with patch.object(lan_mod.rdns_diag, "query_ptr", side_effect=fake):
        assert lan_mod.device_name("192.168.1.9", "192.168.1.1") == "printer.lan"
    assert calls == [("192.168.1.9", 5353), ("192.168.1.1", 53)]
    with patch.object(lan_mod.rdns_diag, "query_ptr", return_value="9.1.168.192.in-addr.arpa"):
        assert lan_mod.device_name("192.168.1.9", None) is None


def test_probe_sends_one_datagram_per_host_and_round():
    sent = []

    class Sock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def setblocking(self, flag):
            pass

        def sendto(self, data, addr):
            sent.append(addr)
            if addr[0].endswith(".3"):
                raise OSError("host is down")

    with (
        patch.object(lan_mod.socket, "socket", return_value=Sock()),
        patch.object(lan_mod.time, "sleep"),
    ):
        lan_mod.probe(["10.0.0.2", "10.0.0.3"], rounds=2)
    assert sent == [("10.0.0.2", 9), ("10.0.0.3", 9)] * 2


def _run_lan(network=None, scan=True, table=None):
    found = (ipaddress.ip_interface("192.168.1.111/24"), "en0", "192.168.1.1", "1a:22:d9:a3:5d:3d")
    table = table if table is not None else lan_mod.parse_arp_an(ARP_AN)
    with (
        patch.object(lan_mod, "local_network", return_value=found),
        patch.object(lan_mod, "probe") as probe,
        patch.object(lan_mod, "neighbours", return_value=table),
        patch.object(lan_mod, "load_vendors", return_value=({"e0a498": "Shenzhen Orfa"}, "/db")),
        patch.object(lan_mod, "device_name", side_effect=lambda ip, router: f"h{ip.split('.')[-1]}"),
    ):
        return lan_mod.lan(network, scan=scan, quiet=True), probe


def test_lan_lists_devices_with_roles():
    r, probe = _run_lan()
    assert r.network == "192.168.1.0/24" and r.scanned == 254
    hosts = probe.call_args.args[0]
    assert "192.168.1.111" not in hosts and len(hosts) == 253
    by_ip = {d.ip: d for d in r.devices}
    assert list(by_ip) == ["192.168.1.1", "192.168.1.103", "192.168.1.111"]  # sorted, no bcast/mcast
    router, phone, me = by_ip.values()
    assert router.is_gateway and router.vendor == "Shenzhen Orfa" and router.name == "h1"
    assert phone.random_mac and phone.vendor is None
    assert me.is_self and me.mac == "1a:22:d9:a3:5d:3d"
    assert evaluate(r) == []


def test_no_scan_only_reads_the_table():
    r, probe = _run_lan(scan=False)
    probe.assert_not_called()
    assert r.scanned == 0 and r.count == 3


def test_explicit_network_limits_and_errors():
    r, _ = _run_lan("10.0.0.0/30", table={"10.0.0.2": "b8:27:eb:00:00:01", "192.168.1.1": "e0:a4:98:05:0e:68"})
    assert r.network == "10.0.0.0/30" and [d.ip for d in r.devices] == ["10.0.0.2"]
    for bad, words in (("10.0.0.0/8", "limit"), ("fe80::/64", "IPv4"), ("banana", "not a network")):
        r, _ = _run_lan(bad)
        assert words in r.error and evaluate(r)


def test_big_subnet_scans_the_part_around_this_machine():
    found = (ipaddress.ip_interface("10.20.30.40/16"), "eth0", None, None)
    with (
        patch.object(lan_mod, "local_network", return_value=found),
        patch.object(lan_mod, "probe"),
        patch.object(lan_mod, "neighbours", return_value={}),
        patch.object(lan_mod, "load_vendors", return_value=({}, None)),
    ):
        r = lan_mod.lan(quiet=True)
    assert r.network == "10.20.28.0/22"


def test_no_local_network():
    with patch.object(lan_mod, "local_network", return_value=None):
        r = lan_mod.lan(quiet=True)
    assert r.error and "no private IPv4 network" in r.error


def test_csv_rows_and_cli():
    r, _ = _run_lan()
    text = export_csv(r)
    assert text.splitlines()[0] == "ip,mac,vendor,name,random_mac,self,gateway"
    args = build_parser().parse_args(["lan", "10.0.0.0/24", "--no-scan", "--no-names"])
    assert args.network == "10.0.0.0/24" and args.no_scan and args.no_names


def test_cmd_lan_passes_options():
    from xping.cli.commands import cmd_lan

    with patch("xping.diagnostics.lan.lan", return_value=LanResult()) as run:
        cmd_lan(build_parser().parse_args(["lan", "-q", "--no-names"]))
    kwargs = run.call_args.kwargs
    assert kwargs["network"] is None and kwargs["scan"] and kwargs["names"] is False


@pytest.mark.parametrize("server", ["127.0.0.1"])
def test_query_ptr_against_a_local_responder(server):
    """rdns.query_ptr talks to any server and port (mDNS uses 5353)."""
    import socket
    import struct
    import threading

    from xping.diagnostics import rdns

    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind((server, 0))

    def answer():
        data, addr = srv.recvfrom(512)
        name = b"\x07printer\x05local\x00"
        reply = data[:2] + b"\x84\x00" + struct.pack("!HHHH", 1, 1, 0, 0) + data[12:]
        reply += b"\xc0\x0c" + struct.pack("!HHIH", 12, 1, 120, len(name)) + name
        srv.sendto(reply, addr)

    threading.Thread(target=answer, daemon=True).start()
    try:
        assert rdns.query_ptr("192.168.1.9", server, port=srv.getsockname()[1], timeout=2) == "printer.local"
    finally:
        srv.close()
