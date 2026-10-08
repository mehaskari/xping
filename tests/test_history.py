"""--save and xping history."""

import importlib
import json
from unittest.mock import patch

import pytest

from xping.cli import commands
from xping.cli.errors import UsageError
from xping.cli.parser import build_parser
from xping.diagnostics import history
from xping.exporters.csv import export_csv
from xping.exporters.json import export_json
from xping.models.ping import PingResult
from xping.models.trace import Hop


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    return tmp_path / "history"


def _ping(avg, n=10):
    return PingResult("example.net", "192.0.2.1", n, [avg] * n)


def test_record_and_show_with_median(store):
    clock = iter(range(1000, 2000, 100))
    with patch.object(history.time, "time", lambda: next(clock)):
        for avg in (20.0, 22.0, 21.0, 30.0):
            history.record("ping", "example.net", _ping(avg), True)
    result = history.show("ping", "example.net")
    assert result.metrics == ["Average RTT", "Jitter", "Packet loss"]
    assert [r.values["Average RTT"] for r in result.runs] == [20.0, 22.0, 21.0, 30.0]
    assert result.median == 21.0 and round(result.latest_vs_median_pct) == 43
    assert result.ok_pct == 100


def test_last_since_and_errors(store):
    clock = iter([100, 200, 300, 400])
    with patch.object(history.time, "time", lambda: next(clock)):
        for avg in (1.0, 2.0, 3.0):
            history.record("ping", "h", _ping(avg), avg != 2.0)
    assert len(history.show("ping", "h", last=2).runs) == 2
    assert len(history.show("ping", "h", since=150, now=400).runs) == 1  # only ts 300
    assert history.show("ping", "h").ok_pct == pytest.approx(66.7, abs=0.1)
    assert "no saved runs" in history.show("ping", "nothing").error


def test_entries_list_targets_with_odd_characters(store):
    history.record("http", "https://example.net/a?b=1", _ping(1.0), True)
    history.record("tcp", "[2001:db8::1]:443", _ping(1.0), False)
    found = {(e.command, e.target) for e in history.entries()}
    assert found == {("http", "https://example.net/a?b=1"), ("tcp", "[2001:db8::1]:443")}
    assert all("/" not in p.name for p in store.rglob("*.jsonl"))  # targets never become paths


def test_lists_like_trace_are_saved(store):
    history.record("trace", "example.net", [Hop(1, None, "10.0.0.1", [1.0])], True)
    run = json.loads((store / "trace" / "example.net.jsonl").read_text())
    assert run["result"][0]["ip"] == "10.0.0.1"
    assert history.show("trace", "example.net").runs[0].values["Hops"] == 1


def test_trim_and_corrupt_lines(store, monkeypatch):
    monkeypatch.setattr(history, "MAX_RUNS", 3)
    for avg in range(5):
        history.record("ping", "h", _ping(float(avg)), True)
    path = store / "ping" / "h.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"broken\n')
    runs = history.show("ping", "h").runs
    assert [r.values["Average RTT"] for r in runs] == [2.0, 3.0, 4.0]


def test_clear(store):
    history.record("ping", "a", _ping(1.0), True)
    history.record("ping", "b", _ping(1.0), True)
    history.record("http", "c", _ping(1.0), True)
    assert history.clear("ping", "a") == 1 and history.clear("ping", "a") == 0
    assert history.clear("ping") == 1
    assert history.clear() == 1 and history.entries() == []


def test_parse_since():
    assert history.parse_since("30m") == 1800 and history.parse_since("2w") == 1209600
    with pytest.raises(ValueError):
        history.parse_since("soon")


def test_main_saves_only_with_flag(store, monkeypatch):
    main_mod = importlib.import_module("xping.cli.main")
    monkeypatch.setitem(main_mod._DISPATCH, "ping", lambda args: _ping(20.0))
    for argv in (["xping", "ping", "example.net"], ["xping", "ping", "example.net", "--save"]):
        with patch("sys.argv", argv), pytest.raises(SystemExit):
            main_mod.main()
    entries = history.entries()
    assert len(entries) == 1 and entries[0].runs == 1  # only the --save run


def test_config_save_true_enables_it(store, tmp_path, monkeypatch):
    import sys

    if sys.version_info < (3, 11):
        pytest.skip("TOML config needs Python 3.11+")
    main_mod = importlib.import_module("xping.cli.main")
    cfg = tmp_path / "config.toml"
    cfg.write_text("[defaults]\nsave = true\n")
    monkeypatch.setenv("XPING_CONFIG", str(cfg))
    monkeypatch.setitem(main_mod._DISPATCH, "tcp", lambda args: _ping(5.0))
    with patch("sys.argv", ["xping", "tcp", "db.local", "5432"]), pytest.raises(SystemExit):
        main_mod.main()
    assert [(e.command, e.target) for e in history.entries()] == [("tcp", "db.local:5432")]


def test_cmd_history_views_and_usage(store, capsys):
    history.record("ping", "prod-db", _ping(20.0), True)
    parser = build_parser()
    listing = commands.cmd_history(parser.parse_args(["history"]))
    assert listing.entries[0].target == "prod-db"
    shown = commands.cmd_history(parser.parse_args(["history", "ping", "prod-db", "--since", "1d"]))
    assert len(shown.runs) == 1
    out = capsys.readouterr().out
    assert "HISTORY" in out and "prod-db" in out  # a profile-style name, not a URL
    with pytest.raises(UsageError, match="--since"):
        commands.cmd_history(parser.parse_args(["history", "ping", "prod-db", "--since", "x"]))
    with pytest.raises(SystemExit):
        parser.parse_args(["history", "lookup", "x"])  # lookup results are not saved


def test_exports(store):
    history.record("ping", "example.net", _ping(20.0), True)
    result = history.show("ping", "example.net")
    assert json.loads(export_json(result))["ok_pct"] == 100
    assert export_csv(result).splitlines()[0] == "ts,ok,Average RTT,Jitter,Packet loss"


def test_save_flag_only_where_supported():
    parser = build_parser()
    assert parser.parse_args(["ping", "h", "--save"]).save
    with pytest.raises(SystemExit):
        parser.parse_args(["lookup", "h", "--save"])


def test_single_run_has_no_trend_and_singular_wording(store, capsys):
    from xping.render.views import history as view

    history.record("ping", "prod-db", _ping(20.0), True)
    with patch("xping.render.COLOR", False), patch("xping.render.ansi.COLOR", False):
        view.print_result(history.show("ping", "prod-db"))
    out = capsys.readouterr().out
    assert "trend" not in out and "100% of 1 run" in out and "1 runs" not in out
    history.record("ping", "prod-db", _ping(25.0), True)
    with patch("xping.render.COLOR", False), patch("xping.render.ansi.COLOR", False):
        view.print_result(history.show("ping", "prod-db"))
    assert "Average RTT trend" in capsys.readouterr().out


def test_save_confirms_except_when_output_must_stay_clean(store, monkeypatch, capsys):
    main_mod = importlib.import_module("xping.cli.main")
    monkeypatch.setitem(main_mod._DISPATCH, "ping", lambda args: _ping(20.0))
    with patch("sys.argv", ["xping", "ping", "prod-db", "--save"]), pytest.raises(SystemExit):
        main_mod.main()
    assert "saved to history (run 1)" in capsys.readouterr().out
    for flag in ("-q", "--json"):
        with patch("sys.argv", ["xping", "ping", "prod-db", "--save", flag]), pytest.raises(SystemExit):
            main_mod.main()
        assert "saved to history" not in capsys.readouterr().out
    assert history.entries()[0].runs == 3  # all three runs were still saved


def test_prune_drops_only_old_runs(tmp_path):
    base = tmp_path / "hist"
    with patch("xping.diagnostics.history.time.time") as clock:
        for day in (1, 5, 9):
            clock.return_value = day * 86400.0
            history.record("ping", "a", PingResult("a", "1.1.1.1", 1, [5.0]), True, base=base)
        clock.return_value = 1 * 86400.0
        history.record("ping", "old", PingResult("old", "1.1.1.1", 1, [5.0]), True, base=base)
    removed = history.prune(3 * 86400, base=base, now=10 * 86400.0)
    assert removed == 3  # days 1 and 5 of "a", and the only run of "old"
    assert [round(r.ts / 86400) for r in history.show("ping", "a", base=base).runs] == [9]
    assert not (base / "ping" / "old.jsonl").exists()  # emptied files are removed
    assert history.prune(3 * 86400, "ping", "a", base=base, now=10 * 86400.0) == 0


def test_cli_clear_older_than(tmp_path, monkeypatch, capsys):
    import importlib

    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "hist")
    main_mod = importlib.import_module("xping.cli.main")
    for argv, code in ((["history", "--older-than", "30d"], 2),
                       (["history", "--clear", "--older-than", "soon"], 2),
                       (["history", "--clear", "--older-than", "30d"], 0)):
        with patch("sys.argv", ["xping", *argv]), pytest.raises(SystemExit) as exc:
            main_mod.main()
        assert exc.value.code == code, argv
    assert "removed 0 saved run(s) older than 30d" in capsys.readouterr().out
