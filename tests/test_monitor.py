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
    for sample in (MonitorSample(1, True, 10), MonitorSample(2, False), MonitorSample(3, True, 20)):
        check.record(sample)
    assert ANSI_RE.sub("", monitor_view.trend(check)) == "▁×█"


@pytest.mark.parametrize("width", [120, 80, 60, 40])
def test_live_lines_never_wrap(width):
    result = MonitorResult(source="checks.toml", started=0)
    for name in ("a very long check name that goes on", "db"):
        check = MonitoredCheck(name, "tcp", "a-really-long-hostname.example.com:5432", 10, "Average connect", "ms")
        for i in range(30):
            check.record(MonitorSample(i, i % 3 != 0, 10.0 + i))
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
        check.record(MonitorSample(1, ok, value))
        check.since, check.detail = 0, detail
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


def test_totals_match_the_full_history_and_memory_stays_bounded():
    import random

    from xping.models import monitor as monitor_model
    from xping.statefilter import outages as confirmed_outages

    rng = random.Random(7)
    runs = monitor_model.KEEP_SAMPLES * 3 + 17
    oks = [rng.random() > 0.3 for _ in range(runs)]
    samples = [MonitorSample(float(i), ok, 10.0 + i % 5 if ok else None) for i, ok in enumerate(oks)]
    check = MonitoredCheck("x", "ping", "h", 1, "Average RTT", "ms", fail_after=2, recover_after=3)
    for sample in samples:
        check.record(sample)
    assert len(check.samples) == monitor_model.KEEP_SAMPLES
    assert check.samples[-1] is samples[-1]
    assert check.checks == runs and check.failures == oks.count(False)
    assert check.up_pct == pytest.approx(oks.count(True) / runs * 100)
    values = [s.value for s in samples if s.value is not None]
    assert check.average == pytest.approx(sum(values) / len(values))
    expected = confirmed_outages([(s.ts, s.ok) for s in samples], 2, 3)
    assert check.outages == len(expected) > 0
    longest = max((end if end is not None else samples[-1].ts) - start for start, end in expected)
    assert check.longest_outage_s == pytest.approx(longest)


def test_samples_given_at_construction_are_recorded():
    check = MonitoredCheck(
        "x", "tcp", "h:1", 5, samples=[MonitorSample(1, True, 3.0), MonitorSample(2, False)]
    )
    assert (check.checks, check.failures, check.up_pct, check.average) == (2, 1, 50.0, 3.0)
    data = check.to_dict()
    assert data["checks"] == 2 and data["failures"] == 1 and len(data["samples"]) == 2
    assert not any(key.startswith("_") for key in data)


def _edit(path, checks):
    """Rewrite a check file: another size, so it counts as changed at once."""
    path.write_text(json.dumps({"checks": checks}, indent=1))


GW = {"name": "gw", "type": "ping", "host": "h1", "every": 10}
DB = {"name": "db", "type": "tcp", "host": "h2", "port": 5432, "every": 10}


def _reloading(tmp_path, first, steps, **options):
    """monitor() on a file that *steps* ({run number: new checks}) rewrites
    between runs. Returns the result and the checks run each time."""
    path = tmp_path / "mon.json"
    path.write_text(json.dumps({"checks": first}))
    clock = Clock()
    calls = []

    def run(entries, workers):
        calls.append([e["name"] for e in entries])
        if len(calls) in steps:
            change = steps[len(calls)]
            change(path) if callable(change) else _edit(path, change)
        return [
            CheckOutcome(e["name"], e["type"], "h", True, "ok", 1.0, None) for e in entries
        ]

    options.setdefault("rounds", 3)
    result = monitor_diag.monitor(
        str(path), quiet=True, clock=clock, sleep=clock.sleep, run=run, **options
    )
    return result, calls


def test_a_new_check_starts_and_the_others_keep_their_numbers(tmp_path):
    result, calls = _reloading(tmp_path, [GW], {1: [GW, DB]})
    assert calls[1] == ["db"]  # the new one at once, gw on its own schedule
    assert [c.name for c in result.checks] == ["gw", "db"]
    assert result.checks[0].checks == 3  # no restart from zero
    assert result.checks[1].checks == 3


def test_a_removed_check_stops(tmp_path):
    result, calls = _reloading(tmp_path, [GW, DB], {1: [DB]})
    assert [c.name for c in result.checks] == ["db"]
    assert calls[1:] == [["db"], ["db"]]


def test_the_same_name_with_another_target_is_a_new_check(tmp_path):
    moved = {**GW, "host": "elsewhere"}
    result, _calls = _reloading(tmp_path, [GW], {2: [moved]})
    assert result.checks[0].target == "elsewhere"
    assert result.checks[0].checks == 3


def test_settings_of_a_running_check_change_in_place(tmp_path):
    changed = {**GW, "every": 60, "fail_after": 4, "recover_after": 2}
    result, _calls = _reloading(tmp_path, [GW], {1: [changed]})
    check = result.checks[0]
    assert (check.every, check.fail_after, check.recover_after) == (60.0, 4, 2)
    assert check._filter.fail_after == 4
    assert check.checks == 3


def test_a_broken_file_changes_nothing_and_is_reported_once(tmp_path, monkeypatch, capsys):
    path = tmp_path / "mon.json"
    path.write_text(json.dumps({"checks": [GW]}))
    clock = Clock()
    calls = []

    def run(entries, workers):
        calls.append(1)
        if len(calls) == 1:
            path.write_text("{ not json")
        return [CheckOutcome("gw", "ping", "h", True, "ok", 1.0, None)]

    result = monitor_diag.monitor(
        str(path), rounds=3, live=False, clock=clock, sleep=clock.sleep, run=run
    )
    assert result.checks[0].checks == 3
    out = capsys.readouterr().out
    assert out.count("not reloaded, the checks keep running") == 1


def test_a_deleted_file_is_not_a_change(tmp_path):
    result, _calls = _reloading(tmp_path, [GW], {1: lambda path: path.unlink()})
    assert result.checks[0].checks == 3


def test_targets_on_the_command_line_have_no_file_to_follow():
    entries = [{"name": "gw", "type": "ping", "host": "h"}]
    clock = Clock()
    run = _runner({"gw": [True]})
    result = monitor_diag.monitor(
        None, entries=entries, rounds=1, quiet=True, clock=clock, sleep=clock.sleep, run=run
    )
    assert result.checks[0].checks == 1


def test_a_long_interval_does_not_delay_a_reload(tmp_path):
    slow = {**GW, "every": 3600}
    path = tmp_path / "mon.json"
    path.write_text(json.dumps({"checks": [slow]}))
    clock = Clock()
    calls = []

    def run(entries, workers):
        calls.append((clock(), [e["name"] for e in entries]))
        if len(calls) == 1:
            _edit(path, [slow, DB])
        return [CheckOutcome(e["name"], e["type"], "h", True, "ok", 1.0, None) for e in entries]

    monitor_diag.monitor(str(path), rounds=2, quiet=True, clock=clock, sleep=clock.sleep, run=run)
    assert calls[1][1] == ["db"]
    assert calls[1][0] - calls[0][0] <= monitor_diag.RELOAD_CHECK


def test_reload_lines(capsys):
    monitor_view.print_reload(None, ["new"], ["old"], 0.0)
    assert "RELOADED" in capsys.readouterr().out
    monitor_view.print_reload(None, [], [], 0.0)
    assert "settings updated" in capsys.readouterr().out
