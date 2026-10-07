"""xping monitor — checks of a check file followed over time (fake clock,
fake checks: nothing sleeps and nothing touches the network)."""

import importlib
import json
from unittest.mock import patch

import pytest

from xping.diagnostics import history
from xping.diagnostics import monitor as monitor_diag
from xping.diagnostics.check import ConfigError
from xping.models.check import CheckOutcome
from xping.models.monitor import MonitoredCheck, MonitorResult, MonitorSample
from xping.models.ping import PingResult
from xping.render.ansi import ANSI_RE
from xping.render.views import monitor as monitor_view
from xping.verdict import evaluate


class Clock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _file(tmp_path, checks, name="mon.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"checks": checks}))
    return str(path)


def _runner(plan):
    """Fake run_entries: *plan* maps a check name to a list of ok values
    (one per run); each pass gets a ping result with a 10 ms RTT."""
    calls = []

    def run(entries, workers):
        calls.append([e["name"] for e in entries])
        outcomes = []
        for e in entries:
            ok = plan[e["name"]].pop(0)
            result = PingResult(host="h", ip="192.0.2.1", count=1, rtts=[10.0 if ok else -1.0])
            detail = "avg 10.0 ms" if ok else "unreachable"
            outcomes.append(CheckOutcome(e["name"], e["type"], "h", ok, detail, 1.0, result))
        return outcomes

    run.calls = calls
    return run


def test_each_check_runs_on_its_own_schedule(tmp_path):
    path = _file(
        tmp_path,
        [
            {"name": "fast", "type": "ping", "host": "a", "every": 10},
            {"name": "slow", "type": "ping", "host": "b", "every": 30},
        ],
    )
    clock = Clock()
    run = _runner({"fast": [True] * 3, "slow": [True] * 3})
    result = monitor_diag.monitor(
        path, rounds=3, quiet=True, clock=clock, sleep=clock.sleep, run=run
    )
    assert run.calls[:4] == [["fast", "slow"], ["fast"], ["fast"], ["slow"]]
    assert [k.checks for k in result.checks] == [3, 3]
    assert clock.now - result.started == pytest.approx(60)
    assert result.ok and evaluate(result) == []
    fast = result.checks[0]
    assert fast.metric == "Average RTT" and fast.unit == "ms" and fast.latest == 10.0


def test_state_changes_outages_and_change_lines(tmp_path, capsys):
    path = _file(tmp_path, [{"name": "db", "type": "ping", "host": "a"}])
    clock = Clock()
    run = _runner({"db": [True, False, False, True, False]})
    result = monitor_diag.monitor(
        path, every=10, rounds=5, live=False, clock=clock, sleep=clock.sleep, run=run
    )
    db = result.checks[0]
    assert [s.ok for s in db.samples] == [True, False, False, True, False]
    assert db.outages == 2 and db.longest_outage_s == pytest.approx(20)
    assert db.up_pct == pytest.approx(40) and db.since == db.samples[-1].ts
    out = ANSI_RE.sub("", capsys.readouterr().out)
    changes = [ln for ln in out.splitlines() if "  ping  " in ln and "│" not in ln]
    assert len(changes) == 4  # first state, down, up, down
    assert "(down for 20s)" in changes[2]
    assert "1 of 1 down at the end: db" in out
    failures = evaluate(result)
    assert failures and "down at the end" in failures[0].message


def test_live_mode_redraws_in_place_and_ctrl_c_ends_with_a_summary(tmp_path, capsys):
    path = _file(tmp_path, [{"name": "web", "type": "ping", "host": "a"}])
    clock = Clock()
    plan = {"web": [True, True]}
    inner = _runner(plan)

    def run(entries, workers):
        if not plan["web"]:
            raise KeyboardInterrupt
        return inner(entries, workers)

    result = monitor_diag.monitor(path, every=5, live=True, clock=clock, sleep=clock.sleep, run=run)
    out = capsys.readouterr().out
    assert "\x1b[1A\x1b[2K" in out  # the table was redrawn in place
    assert "MONITOR SUMMARY" in out and result.checks[0].checks == 2 and result.ended


def test_alerts_fire_on_changes(tmp_path):
    path = _file(tmp_path, [{"name": "db", "type": "ping", "host": "a"}])
    clock = Clock()
    run = _runner({"db": [True, False, True]})
    sent = []
    with patch("xping.diagnostics.notify.desktop_notify", lambda t, m: sent.append(m) or True):
        monitor_diag.monitor(
            path, every=10, rounds=3, notify=True, quiet=True, clock=clock, sleep=clock.sleep,
            run=run,
        )
    assert [m.split(" is ")[1].split()[0] for m in sent] == ["DOWN", "UP"]
    assert sent[0].startswith("db (ping)")


def test_save_writes_each_check_to_its_own_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "hist")
    path = _file(
        tmp_path,
        [
            {"name": "gw", "type": "ping", "host": "10.0.0.1"},
            {"name": "lookup", "type": "lookup", "host": "x"},  # no history for lookup
        ],
    )
    clock = Clock()
    run = _runner({"gw": [True, False], "lookup": [True, True]})
    monitor_diag.monitor(
        path, every=5, rounds=2, save=True, quiet=True, clock=clock, sleep=clock.sleep, run=run
    )
    saved = history.show("ping", "10.0.0.1", base=tmp_path / "hist")
    assert [r.ok for r in saved.runs] == [True, False]
    assert sorted(p.parent.name for p in (tmp_path / "hist").glob("*/*.jsonl")) == ["ping"]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"type": "ping", "host": "a"}, "a"),
        ({"type": "tcp", "host": "db", "port": 5432}, "db:5432"),
        ({"type": "tls", "host": "example.com"}, "example.com"),
        ({"type": "tls", "host": "example.com", "port": 8443}, "example.com:8443"),
        ({"type": "smtp", "host": "mx"}, "mx"),
        ({"type": "http", "url": "https://x/"}, "https://x/"),
        ({"type": "doctor", "target": "internet"}, "internet"),
        ({"type": "doctor", "target": "db"}, "db"),
        ({"type": "wifi", "interface": "default"}, "default"),
        ({"type": "speedtest", "server": "cloudflare"}, "cloudflare"),
        ({"type": "lookup", "host": "x"}, None),
        ({"type": "propagation", "name_to_query": "x"}, None),
    ],
)
def test_history_target_matches_the_single_commands(entry, expected):
    assert monitor_diag.history_target(entry) == expected


@pytest.mark.parametrize("every", [0, -5, "soon"])
def test_invalid_every(tmp_path, every):
    path = _file(tmp_path, [{"type": "ping", "host": "a", "every": every}])
    with pytest.raises(ConfigError, match="every"):
        monitor_diag.monitor(path, quiet=True)


def test_cli_rounds_json_and_exit_code(tmp_path, capsys):
    path = _file(tmp_path, [{"name": "a", "type": "ping", "host": "a"}])
    main_mod = importlib.import_module("xping.cli.main")
    run = _runner({"a": [True, False]})
    clock = Clock()
    real = monitor_diag.monitor

    def fake_monitor(*args, **kwargs):
        return real(*args, **kwargs, clock=clock, sleep=clock.sleep, run=run)

    with (
        patch("xping.diagnostics.monitor.monitor", fake_monitor),
        patch("sys.argv", ["xping", "monitor", path, "--rounds", "2", "--every", "1", "--json"]),
        pytest.raises(SystemExit) as exc,
    ):
        main_mod.main()
    assert exc.value.code == 1
    data = json.loads(capsys.readouterr().out)
    check = data["checks"][0]
    assert check["checks"] == 2 and check["last_ok"] is False and check["outages"] == 1
    assert data["ok"] is False and data["down"] == ["a"]


def test_cli_bad_file_is_a_usage_error(tmp_path):
    main_mod = importlib.import_module("xping.cli.main")
    with (
        patch("sys.argv", ["xping", "monitor", str(tmp_path / "missing.json")]),
        pytest.raises(SystemExit) as exc,
    ):
        main_mod.main()
    assert exc.value.code == 2


def test_view_helpers():
    assert [monitor_view.duration(s) for s in (5, 65, 3725, 90000)] == [
        "5s", "1m05s", "1h02m", "1d01h",
    ]
    assert [monitor_view.duration(s) for s in (60, 3600, 7200, 86400)] == ["1m", "1h", "2h", "1d"]
    assert monitor_view.value_text(12.345, "ms") == "12.3 ms"
    assert monitor_view.value_text(60, "days") == "60 days"
    assert monitor_view.value_text(None, "ms") == "–"
    check = MonitoredCheck("x", "ping", "h", 10, "Average RTT", "ms")
    check.samples = [MonitorSample(1, True, 10), MonitorSample(2, False), MonitorSample(3, True, 20)]
    assert ANSI_RE.sub("", monitor_view.trend(check)) == "▁×█"


@pytest.mark.parametrize("width", [120, 80, 60, 40])
def test_live_lines_never_wrap(width):
    result = MonitorResult(source="checks.toml", started=0)
    for name in ("a very long check name that goes on", "db"):
        check = MonitoredCheck(name, "tcp", "a-really-long-hostname.example.com:5432", 10, "Average connect", "ms")
        check.samples = [MonitorSample(i, i % 3 != 0, 10.0 + i) for i in range(30)]
        check.since, check.detail = 25, "connected in 39.0 ms, and a long detail as well"
        result.checks.append(check)
    for line in monitor_view.live_lines(result, now=60, width=width):
        assert len(ANSI_RE.sub("", line)) <= width - 1


def test_narrow_terminal_shortens_names_then_hides_the_detail():
    result = MonitorResult(source="checks.toml", started=0)
    for name, ok, value, detail in [
        ("Cloudflare HTTPS", True, 124.4, "connected in 124.4 ms"),
        ("Local DB (closed port)", False, None, "127.0.0.1:1 refused or timed out on every attempt"),
    ]:
        check = MonitoredCheck(name, "tcp", "h:1", 5, "Average connect", "ms")
        check.samples, check.since, check.detail = [MonitorSample(1, ok, value)], 0, detail
        result.checks.append(check)
    at_56 = [ANSI_RE.sub("", ln) for ln in monitor_view.live_lines(result, now=10, width=56)]
    assert at_56[0].rstrip().endswith("Detail")
    assert "Local DB (clos…" in at_56[2]  # the name was shortened, not the detail
    assert len(at_56[2].split("0%")[1].strip()) >= 12  # and the detail stays readable
    at_46 = [ANSI_RE.sub("", ln) for ln in monitor_view.live_lines(result, now=10, width=46)]
    assert "Detail" not in at_46[0] and "refused" not in at_46[2]
    assert all(ln == ln.rstrip() for ln in at_46)


def test_not_a_terminal_writes_line_by_line(tmp_path, monkeypatch):
    """`xping monitor >> log` must show up in `tail -f log` right away."""
    calls = []

    class Stdout:
        def isatty(self):
            return False

        def reconfigure(self, **kwargs):
            calls.append(kwargs)

        def write(self, text):
            return len(text)

        def flush(self):
            pass

    monkeypatch.setattr("sys.stdout", Stdout())
    path = _file(tmp_path, [{"name": "a", "type": "ping", "host": "a"}])
    clock = Clock()
    monitor_diag.monitor(path, rounds=1, clock=clock, sleep=clock.sleep, run=_runner({"a": [True]}))
    assert {"line_buffering": True} in calls


@pytest.mark.parametrize("colour", [False, True])
def test_change_lines_line_up(tmp_path, capsys, colour):
    path = _file(
        tmp_path,
        [
            {"name": "db", "type": "tcp", "host": "a", "port": 1},
            {"name": "a much longer check name", "type": "ping", "host": "b"},
        ],
    )
    clock = Clock()
    run = _runner({"db": [True], "a much longer check name": [False]})
    with patch("xping.render.ansi.COLOR", colour), patch("xping.render.COLOR", colour):
        monitor_diag.monitor(path, rounds=1, live=False, clock=clock, sleep=clock.sleep, run=run)
    lines = [ANSI_RE.sub("", ln) for ln in capsys.readouterr().out.splitlines()]
    changes = [ln for ln in lines if ln.startswith("  19") and ("UP" in ln or "DOWN" in ln)]
    assert len(changes) == 2
    # the type column (and so the detail after it) starts at the same place
    assert len({ln.index(" tcp ") if " tcp " in ln else ln.index(" ping ") for ln in changes}) == 1
