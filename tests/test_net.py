"""xping net — interface, route, resolver and public-IP parsing."""

from unittest.mock import patch

from xping.diagnostics import net as net_diag
from xping.models.net import NetInterface, NetResult

IP_LINK = """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000\\    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: tunl0@NONE: <NOARP> mtu 1480 qdisc noop state DOWN mode DEFAULT group default qlen 1000\\    link/ipip 0.0.0.0 brd 0.0.0.0
11: eth0@if17: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default \\    link/ether 02:e6:59:17:52:30 brd ff:ff:ff:ff:ff:ff link-netnsid 0
"""
IP_ADDR = """\
1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever
11: eth0    inet 172.17.0.2/16 brd 172.17.255.255 scope global eth0\\       valid_lft forever preferred_lft forever
11: eth0    inet6 fe80::e6:59ff:fe17:5230/64 scope link \\       valid_lft forever preferred_lft forever
"""
IFCONFIG = """\
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
\tinet6 ::1 prefixlen 128
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 1a:22:d9:a3:5d:3d
\tinet6 fe80::14cb:4b64:4151:35%en0 prefixlen 64 secured scopeid 0xb
\tinet 192.168.1.106 netmask 0xffffff00 broadcast 192.168.1.255
\tstatus: active
en1: flags=8822<BROADCAST,SMART,SIMPLEX,MULTICAST> mtu 1500
\tstatus: inactive
"""
IPCONFIG = """\
Windows IP Configuration

   Host Name . . . . . . . . . . . . : DESKTOP

Ethernet adapter Ethernet:

   Connection-specific DNS Suffix  . : lan
   Physical Address. . . . . . . . . : 00-15-5D-01-02-03
   Link-local IPv6 Address . . . . . : fe80::1c2b:3a4d:5e6f:7081%12(Preferred)
   IPv4 Address. . . . . . . . . . . : 192.168.1.50(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : fe80::1%12
                                       192.168.1.1
   DNS Servers . . . . . . . . . . . : 1.1.1.1
                                       8.8.8.8

Wireless LAN adapter Wi-Fi:

   Media State . . . . . . . . . . . : Media disconnected
   Physical Address. . . . . . . . . : AA-BB-CC-DD-EE-FF
"""


def test_linux_ip_parsing():
    ifaces = net_diag.parse_ip_link(IP_LINK)
    assert set(ifaces) == {"lo", "tunl0", "eth0"}  # "@if17" suffix stripped
    assert ifaces["eth0"].state == "up" and ifaces["eth0"].mtu == 1500
    assert ifaces["eth0"].mac == "02:e6:59:17:52:30" and ifaces["tunl0"].state == "down"
    net_diag.parse_ip_addr(IP_ADDR, ifaces)
    assert ifaces["eth0"].addresses == ["172.17.0.2/16", "fe80::e6:59ff:fe17:5230/64"]
    assert ifaces["lo"].loopback and not ifaces["eth0"].loopback
    assert net_diag.parse_ip_route("default via 172.17.0.1 dev eth0 proto dhcp") == (
        "172.17.0.1",
        "eth0",
    )
    assert net_diag.parse_ip_route("") == (None, None)


def test_resolv_conf():
    text = "# comment\nnameserver 127.0.0.53\nnameserver 1.1.1.1\nnameserver 1.1.1.1\nsearch lan\n"
    assert net_diag.parse_resolv_conf(text) == ["127.0.0.53", "1.1.1.1"]


def test_macos_parsing():
    ifaces = {i.name: i for i in net_diag.parse_ifconfig(IFCONFIG)}
    assert ifaces["en0"].addresses == ["fe80::14cb:4b64:4151:35/64", "192.168.1.106/24"]
    assert ifaces["en0"].mtu == 1500 and ifaces["en0"].mac == "1a:22:d9:a3:5d:3d"
    assert ifaces["lo0"].addresses[0] == "127.0.0.1/8"
    assert ifaces["en1"].state == "down"
    route = "   route to: default\n    gateway: 192.168.1.1\n  interface: en0\n"
    assert net_diag.parse_route_get(route) == ("192.168.1.1", "en0")
    scutil = "resolver #1\n  nameserver[0] : 5.202.100.100\n  nameserver[1] : 8.8.8.8\nresolver #2\n  nameserver[0] : 8.8.8.8\n"
    assert net_diag.parse_scutil_dns(scutil) == ["5.202.100.100", "8.8.8.8"]


def test_windows_ipconfig():
    ifaces, gateways, dns = net_diag.parse_ipconfig(IPCONFIG)
    by_name = {i.name: i for i in ifaces}
    eth = by_name["Ethernet"]
    assert eth.addresses == ["fe80::1c2b:3a4d:5e6f:7081", "192.168.1.50"]
    assert eth.mac == "00:15:5d:01:02:03" and eth.state == "up"
    assert by_name["Wi-Fi"].state == "down"
    assert gateways == ["fe80::1", "192.168.1.1"] and dns == ["1.1.1.1", "8.8.8.8"]


def test_cf_trace():
    parsed = net_diag.parse_cf_trace("fl=1\nip=203.0.113.9\nloc=DE\ncolo=FRA\n")
    assert parsed["ip"] == "203.0.113.9" and parsed["colo"] == "FRA"


def _fill(result):
    result.interfaces = [NetInterface("eth0", "up", 1500, None, ["10.0.0.5/24"])]
    result.gateway_ipv4, result.gateway_interface = "10.0.0.1", "eth0"
    result.dns_servers = ["10.0.0.1"]


def test_net_collects_everything(capsys):
    traces = {
        net_diag._TRACE_V4: {"ip": "203.0.113.9", "loc": "DE", "colo": "FRA"},
        net_diag._TRACE_V6: {},
    }
    with (
        patch.object(net_diag, "_linux", side_effect=_fill),
        patch.object(net_diag, "_darwin", side_effect=_fill),
        patch.object(net_diag, "_windows", side_effect=_fill),
        patch.object(net_diag, "_cf_trace", side_effect=lambda url: traces[url]),
        patch.object(net_diag, "local_address", return_value="10.0.0.5"),
        patch("sys.stdout.isatty", return_value=False),
        patch("xping.render.COLOR", False),
    ):
        result = net_diag.net()
    out = capsys.readouterr().out
    assert result.public_ipv4 == "203.0.113.9" and result.public_ipv6 is None
    assert "203.0.113.9  (DE, via FRA)" in out and "10.0.0.5/24" in out
    assert "no IPv6 connectivity" in out


def test_net_no_public_skips_http():
    with (
        patch.object(net_diag, "_linux", side_effect=_fill),
        patch.object(net_diag, "_darwin", side_effect=_fill),
        patch.object(net_diag, "_windows", side_effect=_fill),
        patch.object(net_diag, "_cf_trace") as trace,
        patch.object(net_diag, "local_address", return_value=None),
    ):
        result = net_diag.net(public=False, quiet=True)
    trace.assert_not_called()
    assert result.public_ipv4 is None and result.error is None


def test_net_error_when_nothing_found():
    from xping.cli.verdict import evaluate

    with (
        patch.object(net_diag, "_linux"),
        patch.object(net_diag, "_darwin"),
        patch.object(net_diag, "_windows"),
        patch.object(net_diag, "local_address", return_value=None),
    ):
        result = net_diag.net(public=False, quiet=True)
    assert result.error and evaluate(result)
    assert evaluate(NetResult(hostname="h")) == []


def test_view_hides_link_local_only_interfaces(capsys):
    from xping.render.views import net as net_view

    result = NetResult(
        hostname="h",
        interfaces=[
            NetInterface("en0", "up", 1500, None, ["fe80::1/64", "192.168.1.2/24"]),
            NetInterface("utun0", "up", 1380, None, ["fe80::2/64"]),
        ],
    )
    with patch("xping.render.COLOR", False):
        net_view.print_result(result, public=False)
    out = capsys.readouterr().out
    assert "192.168.1.2/24" in out and "utun0" not in out and "1 interface(s)" in out
    assert out.index("192.168.1.2/24") < out.index("fe80::1/64")  # IPv4 listed first
