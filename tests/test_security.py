"""Security regressions: hostile servers, hostile names, hostile local files."""

import json
import socket
import struct
import threading
from unittest.mock import MagicMock, patch

import pytest

from xping.render import ansi


def _finishes(fn, seconds=3.0):
    """Run fn in a thread; fail if it is still running after *seconds*."""
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("value", fn()), daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), "hung (infinite loop)"
    return box.get("value")


# ── DNS: compression-pointer loops must not hang the parser ─────────────────


def _looping_response(qtype: int, rtype: int) -> bytes:
    question = b"\x07example\x03net\x00" + struct.pack("!HH", qtype, 1)
    header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
    answer_rdata_at = 12 + len(question) + 12
    rdata = struct.pack("!H", 0xC000 | answer_rdata_at)  # a name that points at itself
    answer = b"\xc0\x0c" + struct.pack("!HHIH", rtype, 1, 60, len(rdata)) + rdata
    return header + question + answer


def test_lookup_parser_survives_pointer_loop():
    from xping.diagnostics.lookup import _parse_dns_response

    assert _finishes(lambda: _parse_dns_response(_looping_response(2, 2), 2)) is not None


def test_rdns_parser_survives_pointer_loop():
    from xping.diagnostics.rdns import _parse_ptr_response

    assert _finishes(lambda: _parse_ptr_response(_looping_response(12, 12))) is not None


def test_truncated_pointer_does_not_crash():
    from xping.diagnostics.lookup import _parse_dns_response

    data = _looping_response(2, 2)[:-1]  # cut the pointer in half
    _parse_dns_response(data, 2)


def test_dnssec_malformed_response_is_valueerror():
    from xping.diagnostics import dnssec

    with pytest.raises(ValueError):
        dnssec.parse_response(struct.pack("!HHHHHH", 1, 0x8180, 1, 1, 0, 0) + b"\x03abc")


# ── DNS: raw queries use a random ID and ignore unmatched replies ───────────


def test_raw_query_ignores_reply_with_wrong_id():
    from xping.diagnostics import lookup

    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def serve():
        query, addr = server.recvfrom(512)
        ident = struct.unpack("!H", query[:2])[0]
        forged = struct.pack("!H", ident ^ 0xFFFF) + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
        server.sendto(forged + query[12:] + b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\x06\x06\x06\x06", addr)
        real = query[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
        server.sendto(real + query[12:] + b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\x01\x02\x03\x04", addr)

    threading.Thread(target=serve, daemon=True).start()
    real_socket = socket.socket

    class PortSocket(real_socket):
        def connect(self, address):
            super().connect((address[0], port))

    with patch.object(lookup.socket, "socket", PortSocket):
        status, records = lookup._raw_query("example.net", 1, "127.0.0.1", timeout=2)
    server.close()
    assert (status, records) == ("NOERROR", ["1.2.3.4"])  # the forged 6.6.6.6 was dropped


def test_query_ids_are_random():
    from xping.diagnostics import lookup

    sent = []

    class Capture:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

        def connect(self, addr):
            pass

        def send(self, data):
            sent.append(data[:2])

        def recv(self, n):
            raise TimeoutError

    with patch.object(lookup.socket, "socket", Capture):
        for _ in range(8):
            lookup._raw_query("example.net", 1, "192.0.2.53", timeout=0.01)
    assert len(set(sent)) > 1


# ── dig: a hostile name can never become an option ───────────────────────────


def test_dig_name_cannot_be_an_option():
    from xping.diagnostics import lookup

    with patch.object(lookup.subprocess, "run") as run:
        run.return_value = MagicMock(stdout=";; ->>HEADER<<- status: NXDOMAIN")
        lookup._dig_query("-f/etc/passwd", "A", "9.9.9.9")
    cmd = run.call_args.args[0]
    assert cmd[-4:] == ["-t", "A", "-q", "-f/etc/passwd"]  # -q makes it a query name
    assert "-f/etc/passwd" not in cmd[:-1]


# ── terminal output: server data cannot drive the terminal ──────────────────

EVIL = "ok\x1b]52;c;cm0gLXJm\x07\x1b[2A\x1b[2Kfake\r\x08\x9b31m\x1b[8mhidden\x1b[30mblack"


@pytest.mark.parametrize("colour", [True, False])
def test_safe_strips_everything_but_own_colours(colour, monkeypatch):
    monkeypatch.setattr(ansi, "COLOR", colour)
    cleaned = ansi.safe(EVIL + ansi.BRAND_MINT + "green" + ansi.RESET)
    assert "\x1b]" not in cleaned and "\x1b[2A" not in cleaned and "\x1b[2K" not in cleaned
    assert "\x1b[8m" not in cleaned and "\x1b[30m" not in cleaned
    assert "\r" not in cleaned and "\x08" not in cleaned and "\x9b" not in cleaned
    assert ("\x1b[38;2;130;255;190m" in cleaned) is colour  # our own colour survives


def test_c_kv_and_tables_sanitize(monkeypatch, capsys):
    from xping.render.layout import kv
    from xping.render.tables import print_table

    monkeypatch.setattr(ansi, "COLOR", True)
    assert "\x1b]52" not in ansi.c(EVIL, ansi.BOLD)
    assert "\x1b[2A" not in kv("Banner", EVIL)
    print_table(["Header"], [[EVIL]])
    assert "\x1b]52" not in capsys.readouterr().out


def test_exports_strip_control_characters():
    from xping.exporters.tables import cell

    assert cell(EVIL) == ansi.safe(EVIL, keep_colors=False)
    assert "\x1b" not in cell(EVIL) and "\r" not in cell(EVIL)


# ── local files: hand-edited profiles, rc files ──────────────────────────────


def test_profile_names_output_only_valid_names(tmp_path, monkeypatch, capsys):
    from xping.cli import commands
    from xping.cli.parser import build_parser
    from xping.diagnostics import profile as profile_diag

    store = tmp_path / "profiles.json"
    store.write_text(json.dumps({
        "db": {"target": "10.0.0.5"},
        "$(touch pwned)": {"target": "1.1.1.1"},  # bash compgen -W would run this
    }))
    monkeypatch.setattr(profile_diag, "STORE_DIR", tmp_path)
    monkeypatch.setattr(profile_diag, "STORE_FILE", store)
    commands.cmd_profile(build_parser().parse_args(["profile", "list", "--names"]))
    assert capsys.readouterr().out.split() == ["db"]


def test_rc_block_quotes_the_script_path(tmp_path):
    from xping.cli import completion

    home = tmp_path / "we$(ird) it's home"  # $, space and a quote — all valid on Windows too
    home.mkdir()
    completion.install("zsh", home=home)
    block = (home / ".zshrc").read_text()
    line = next(ln for ln in block.splitlines() if ln.startswith("source "))
    assert line.startswith("source '") and "$(ird)" in line  # single-quoted: never expanded


# ── resource limits: endless responses stop ──────────────────────────────────


def test_http_body_is_counted_not_stored_and_capped(monkeypatch):
    from xping.diagnostics import http as http_diag

    monkeypatch.setattr(http_diag, "MAX_BODY", 200_000)
    resp = MagicMock(status=200, reason="OK", version=11)
    resp.getheaders.return_value = []
    resp.getheader.return_value = None
    resp.read.return_value = b"x" * 65536  # never ends
    conn = MagicMock()
    conn.getresponse.return_value = resp
    with (
        patch.object(http_diag.socket, "create_connection"),
        patch.object(http_diag.http.client, "HTTPConnection", return_value=conn),
        patch.object(http_diag.socket, "gethostbyname", return_value="192.0.2.1"),
    ):
        d = _finishes(lambda: http_diag._one_request("http://big.test/", 1.0))
    assert d["body_truncated"] and 200_000 <= d["body_bytes"] < 300_000


def test_whois_response_is_capped(monkeypatch):
    from xping.diagnostics import whois

    monkeypatch.setattr(whois, "MAX_RESPONSE", 50_000)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    stop = threading.Event()

    def serve():
        conn, _ = server.accept()
        conn.recv(512)
        try:
            while not stop.is_set():
                conn.sendall(b"A" * 4096)
        except OSError:
            pass
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    with patch.object(whois.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", port))]):
        text = _finishes(lambda: whois._query("whois.test", "example.net", 2.0), 5)
    stop.set()
    server.close()
    assert 50_000 <= len(text) < 60_000
