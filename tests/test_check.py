"""xping check — batch checks from a TOML/JSON file."""

import json
import sys
from unittest.mock import patch

import pytest

from xping.verdict import evaluate
from xping.diagnostics import check as check_diag
from xping.models.ping import PingResult
from xping.models.tcp import TcpAttempt, TcpResult

needs_tomllib = pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib is 3.11+")


def _write(tmp_path, name, text, encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return str(path)


@needs_tomllib
def test_example_config_is_valid(tmp_path):
    entries = check_diag.load_config(_write(tmp_path, "c.toml", check_diag.EXAMPLE))
    assert [e["type"] for e in entries] == ["ping", "tcp", "http", "tls", "dnscheck", "ntp", "propagation"]
    assert all(e["timeout"] == 3 for e in entries)  # [defaults] merged into every check


def test_json_config_and_default_names(tmp_path):
    cfg = {"defaults": {"timeout": 1}, "checks": [{"type": "TCP", "host": "db", "port": 5432}]}
    entries = check_diag.load_config(_write(tmp_path, "c.json", json.dumps(cfg)))
    assert entries[0]["type"] == "tcp" and entries[0]["name"] == "tcp db"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"checks": []}', "at least one"),
        ('{"checks": [{"type": "nope"}]}', "unknown type"),
        ('{"checks": [{"type": "tcp", "host": "h"}]}', "missing port"),
        ("not json", "invalid JSON"),
        ('{"checks": ["x"]}', "must be a table"),
    ],
)
def test_config_errors(tmp_path, text, message):
    with pytest.raises(check_diag.ConfigError, match=message):
        check_diag.load_config(_write(tmp_path, "c.json", text))


def test_missing_file():
    with pytest.raises(check_diag.ConfigError, match="cannot read"):
        check_diag.load_config("/definitely/not/here.json")


def test_run_checks_judges_with_thresholds_and_isolates_errors(tmp_path, capsys):
    cfg = {
        "checks": [
            {"name": "fast ping", "type": "ping", "host": "a", "max_latency": 50},
            {"name": "slow ping", "type": "ping", "host": "b", "max_latency": 50},
            {"name": "db", "type": "tcp", "host": "prod-db", "port": 5432},
            {"name": "broken", "type": "http", "url": "https://x"},
        ]
    }
    path = _write(tmp_path, "c.json", json.dumps(cfg))

    def fake_ping(host, **_kw):
        rtt = 10.0 if host == "a" else 200.0
        return PingResult(host=host, ip="1.2.3.4", count=1, rtts=[rtt])

    def fake_tcp(host, port, **_kw):
        assert host == "10.0.0.5"  # profile name resolved
        return TcpResult(host=host, port=port, ip=host, attempts=[TcpAttempt(1, True, 4.0)])

    with (
        patch("xping.diagnostics.ping.ping", side_effect=fake_ping),
        patch("xping.diagnostics.tcp.tcp", side_effect=fake_tcp),
        patch("xping.diagnostics.http.http_diagnose", side_effect=RuntimeError("kaboom")),
        patch.object(check_diag.profile_diag, "resolve_target", side_effect=lambda v: {"prod-db": "10.0.0.5"}.get(v, v)),
        patch("sys.stdout.isatty", return_value=False),
        patch("xping.render.COLOR", False),
    ):
        report = check_diag.run_checks(path)
    by_name = {o.name: o for o in report.outcomes}
    assert by_name["fast ping"].ok and not by_name["slow ping"].ok
    assert "max-latency" in by_name["slow ping"].detail
    assert by_name["db"].ok and by_name["db"].target == "prod-db:5432"  # shown as configured
    assert not by_name["broken"].ok and by_name["broken"].detail == "error: kaboom"
    assert report.failed == 2 and evaluate(report)
    out = capsys.readouterr().out
    assert "2 of 4 checks failed" in out


def test_cli_example_and_missing_file(capsys):
    from xping.cli import commands
    from xping.cli.errors import UsageError
    from xping.cli.parser import build_parser

    assert commands.cmd_check(build_parser().parse_args(["check", "--example"])) is True
    assert "[[check]]" in capsys.readouterr().out
    with pytest.raises(UsageError):
        commands.cmd_check(build_parser().parse_args(["check"]))


def test_example_is_ascii():
    assert check_diag.EXAMPLE.isascii()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_config_encodings(tmp_path, encoding):
    """PowerShell 5 redirection writes UTF-16 with a BOM; UTF-8 BOMs are common too."""
    cfg = '{"checks": [{"type": "ping", "host": "h", "name": "caf\u00e9"}]}'
    entries = check_diag.load_config(_write(tmp_path, "c.json", cfg, encoding))
    assert entries[0]["name"] == "caf\u00e9"


def test_config_undecodable(tmp_path):
    path = tmp_path / "c.json"
    path.write_bytes(b'{"checks": [\x97]}')
    with pytest.raises(check_diag.ConfigError, match="not UTF-8"):
        check_diag.load_config(str(path))


def test_new_types_defaults_and_summaries(tmp_path, capsys):
    from xping.models.doctor import DoctorResult
    from xping.models.mtr import MtrHop, MtrResult
    from xping.models.speedtest import SpeedResult
    from xping.models.trace import Hop
    from xping.models.wifi import WifiNetwork, WifiResult

    cfg = {
        "checks": [
            {"type": "trace", "host": "h", "tcp": True},
            {"type": "mtr", "host": "h", "max_loss": 10},
            {"type": "wifi", "min_signal": -70},
            {"type": "doctor"},
            {"type": "speedtest", "min_download": 50},
        ]
    }
    path = _write(tmp_path, "c.json", json.dumps(cfg))
    entries = check_diag.load_config(path)
    assert [e["name"] for e in entries] == [
        "trace h", "mtr h", "wifi default", "doctor internet", "speedtest cloudflare",
    ]
    calls = []
    hops = [Hop(1, None, "10.0.0.1", [1.0]), Hop(2, None, "9.9.9.9", [12.0])]
    mtr = MtrResult(host="h", dest_ip="9.9.9.9", cycles=5,
                    hops=[MtrHop(1, "10.0.0.1", rtts=[1.0] * 5), MtrHop(2, "9.9.9.9", rtts=[9.0] * 5)])
    wifi = WifiResult(connected=True, current=WifiNetwork(ssid="home", signal_dbm=-75))
    doc = DoctorResult(diagnosis="Everything works")
    speed = SpeedResult(download_mbps=120.0, upload_mbps=20.0)

    def fake_trace(**kw):
        calls.append(("trace", kw["tcp_port"], kw["probes"]))
        return hops

    def fake_speed(**kw):
        calls.append(("speedtest",))
        return speed

    with (
        patch("xping.diagnostics.trace.trace", side_effect=fake_trace),
        patch("xping.diagnostics.mtr.mtr", return_value=mtr),
        patch("xping.diagnostics.wifi.wifi", return_value=wifi),
        patch("xping.diagnostics.doctor.doctor", return_value=doc) as fake_doctor,
        patch("xping.diagnostics.speedtest.speedtest", side_effect=fake_speed),
    ):
        report = check_diag.run_checks(path, quiet=True)
    by_type = {o.type: o for o in report.outcomes}
    assert [o.type for o in report.outcomes] == ["trace", "mtr", "wifi", "doctor", "speedtest"]
    assert calls[0] == ("trace", 443, 1) and calls[-1] == ("speedtest",)  # speedtest runs last
    assert fake_doctor.call_args.kwargs["target"] is None
    assert by_type["trace"].ok and by_type["trace"].detail == "2 hops to 9.9.9.9, 12.0 ms"
    assert by_type["mtr"].ok and "0% loss" in by_type["mtr"].detail
    assert not by_type["wifi"].ok and "--min-signal" in by_type["wifi"].detail
    assert by_type["doctor"].ok and by_type["doctor"].detail == "Everything works"
    assert by_type["speedtest"].ok and by_type["speedtest"].detail.startswith("↓ 120.0")


def test_speedtest_thresholds():
    from xping.models.speedtest import SpeedResult
    from xping.cli.parser import build_parser

    args = build_parser().parse_args(["speedtest", "--min-download", "100", "--min-upload", "10"])
    failures = evaluate(SpeedResult(download_mbps=80.0, upload_mbps=None), args)
    assert [f.message for f in failures] == [
        "download 80.0 Mbit/s is below --min-download 100",
        "upload failed is below --min-upload 10",
    ]
    assert all(f.threshold for f in failures)
    assert evaluate(SpeedResult(download_mbps=150.0, upload_mbps=12.0), args) == []


def test_check_save_records_the_report(tmp_path, monkeypatch):
    import importlib

    from xping.diagnostics import history

    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "hist")
    cfg = {"checks": [{"type": "ping", "host": "a"}]}
    path = _write(tmp_path, "c.json", json.dumps(cfg))
    good = PingResult(host="a", ip="1.1.1.1", count=1, rtts=[5.0])
    main_mod = importlib.import_module("xping.cli.main")
    with (
        patch("xping.diagnostics.ping.ping", return_value=good),
        patch("sys.argv", ["xping", "check", path, "--save", "-q"]),
        pytest.raises(SystemExit) as exc,
    ):
        main_mod.main()
    assert exc.value.code == 0
    saved = list((tmp_path / "hist" / "check").glob("*.jsonl"))
    assert len(saved) == 1
    run = json.loads(saved[0].read_text().splitlines()[0])
    assert run["ok"] and run["target"].endswith("c.json")
