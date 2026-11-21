"""xping listen: owning processes on macOS (lsof) and Windows (tasklist)."""

from unittest.mock import patch

from xping.diagnostics import listen as listen_mod
from xping.models.listen import ListenEntry

MAC_NETSTAT = """\
Active Internet connections (including servers)
Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)
tcp4       0      0  127.0.0.1.5432         *.*                    LISTEN
tcp46      0      0  *.8088                 *.*                    LISTEN
tcp4       0      0  127.0.0.1.8021         *.*                    LISTEN
tcp4       0      0  192.168.1.5.50000      17.1.1.1.443           ESTABLISHED
udp4       0      0  *.5353                 *.*
"""

LSOF_TCP = """\
p1861
ccom.docker.backend
f20
PTCP
n127.0.0.1:5432
f21
PTCP
n*:8088
p88
cGoogle Chrome Helper
f30
PTCP
n192.168.1.5:50000->17.1.1.1:443
"""

LSOF_UDP = """\
p300
cmDNSResponder
f5
PUDP
n*:5353
f6
PUDP
n[::]:5353
"""

WIN_NETSTAT = """\
  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1032
  TCP    [::]:445               [::]:0                 LISTENING       4
  TCP    10.0.0.2:51000         20.1.1.1:443           ESTABLISHED     7720
  UDP    0.0.0.0:123            *:*                                    1580
"""

TASKLIST = '''\
"System","4","Services","0","144 K"
"svchost.exe","1032","Services","0","12,004 K"
"svchost.exe","1580","Services","0","9,880 K"
'''


def test_parse_lsof_skips_connections_and_keeps_full_names():
    owners = listen_mod._parse_lsof(LSOF_TCP + LSOF_UDP)
    assert owners[("tcp", 5432)] == [("127.0.0.1", 1861, "com.docker.backend")]
    assert owners[("tcp", 8088)] == [("*", 1861, "com.docker.backend")]
    assert ("tcp", 50000) not in owners  # an outgoing connection
    assert owners[("udp", 5353)] == [("*", 300, "mDNSResponder"), ("::", 300, "mDNSResponder")]


def test_fill_owners_prefers_the_same_address():
    entries = [ListenEntry("tcp", "127.0.0.1", 80), ListenEntry("tcp", "*", 81)]
    owners = {
        ("tcp", 80): [("*", 1, "other"), ("127.0.0.1", 2, "nginx")],
        ("tcp", 81): [("::", 3, "caddy")],
    }
    listen_mod._fill_owners(entries, owners)
    assert (entries[0].pid, entries[0].process) == (2, "nginx")
    assert (entries[1].pid, entries[1].process) == (3, "caddy")


def test_macos_listen_names_processes_and_explains_the_gaps():
    def fake_run(*cmd):
        if cmd[0] == "ss":
            return None
        if cmd[0] == "netstat":
            return MAC_NETSTAT
        return LSOF_TCP if "-iTCP" in cmd else LSOF_UDP

    with (
        patch.object(listen_mod, "_run", side_effect=fake_run),
        patch.object(listen_mod.sys, "platform", "darwin"),
        patch.object(listen_mod.os, "geteuid", return_value=501, create=True),
    ):
        result = listen_mod.listen(quiet=True)
    by_port = {(e.proto, e.local_port): e for e in result.entries}
    assert by_port[("tcp", 5432)].process == "com.docker.backend"
    assert by_port[("udp", 5353)].pid == 300
    assert by_port[("tcp", 8021)].process is None  # another user's process
    assert result.note and "sudo" in result.note


def test_no_note_when_every_process_is_known_or_as_root():
    def fake_run(*cmd):
        return None if cmd[0] == "ss" else (MAC_NETSTAT if cmd[0] == "netstat" else "")

    with (
        patch.object(listen_mod, "_run", side_effect=fake_run),
        patch.object(listen_mod.sys, "platform", "darwin"),
        patch.object(listen_mod.os, "geteuid", return_value=0, create=True),
    ):
        assert listen_mod.listen(quiet=True).note is None


def test_windows_netstat_ano_and_tasklist():
    def fake_run(*cmd):
        return {"netstat": WIN_NETSTAT, "tasklist": TASKLIST}[cmd[0]]

    with (
        patch.object(listen_mod, "_run", side_effect=fake_run),
        patch.object(listen_mod.sys, "platform", "win32"),
    ):
        result = listen_mod.listen(quiet=True)
    got = {(e.proto, e.local_port): (e.pid, e.process) for e in result.entries}
    assert got == {
        ("tcp", 135): (1032, "svchost.exe"),
        ("tcp", 445): (4, "System"),
        ("udp", 123): (1580, "svchost.exe"),
    }
    assert result.note is None


def test_windows_falls_back_to_netstat_an():
    plain = "\n".join(line.rsplit(None, 1)[0] for line in WIN_NETSTAT.splitlines()[1:])
    calls = []

    def fake_run(*cmd):
        calls.append(cmd)
        if cmd == ("netstat", "-ano"):
            return None
        return plain if cmd[0] == "netstat" else ""

    with (
        patch.object(listen_mod, "_run", side_effect=fake_run),
        patch.object(listen_mod.sys, "platform", "win32"),
    ):
        result = listen_mod.listen(quiet=True)
    assert ("netstat", "-an") in calls and result.count == 3
    assert all(e.pid is None for e in result.entries)


def test_parse_tasklist_ignores_junk():
    assert listen_mod._parse_tasklist('INFO: No tasks\n"a.exe","12"\n"b","x"\n') == {12: "a.exe"}
