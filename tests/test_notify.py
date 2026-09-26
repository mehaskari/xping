"""--notify / --webhook: down/up events in watch mode."""

from unittest.mock import patch

import pytest

from xping.cli import commands
from xping.cli.errors import UsageError
from xping.cli.parser import build_parser
from xping.diagnostics import notify
from xping.diagnostics.notify import Notifier
from xping.diagnostics.watch import watch

REAL_DESKTOP_NOTIFY = notify.desktop_notify  # before the fixture replaces it


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _notifier(clock=None, **kw):
    n = Notifier("db:5432", "tcp", clock=clock or Clock(), **kw)
    n.desktop = n.desktop or not n.webhook  # enabled, but deliver nowhere by default
    return n


@pytest.fixture(autouse=True)
def no_delivery(monkeypatch):
    monkeypatch.setattr(notify, "desktop_notify", lambda title, message: True)
    monkeypatch.setattr(notify, "post_webhook", lambda url, payload: None)


def test_first_check_is_only_a_baseline():
    n = _notifier()
    n.observe(True, None, "connected")
    n.observe(False, None, "refused")
    assert n.sent == []


def test_down_and_up_events_with_outage_duration():
    clock = Clock()
    n = _notifier(clock)
    n.observe(True, None)
    clock.now += 5
    n.observe(False, True, "refused")
    n.observe(False, False, "refused")  # still down: no repeat
    clock.now += 125
    n.observe(True, False, "connected", 1.23456)
    assert [e["event"] for e in n.sent] == ["down", "up"]
    assert n.sent[0]["text"] == "🔴 xping: db:5432 (tcp) is DOWN — refused"
    up = n.sent[1]
    assert up["text"] == "🟢 xping: db:5432 (tcp) is UP again after 2m05s — connected"
    assert up["content"] == up["text"] and up["latency_ms"] == 1.235
    assert up["target"] == "db:5432" and up["check"] == "tcp" and up["source"] == "xping"


def test_until_up_success_always_announced():
    n = _notifier()
    n.observe(True, None, "connected", final=True)
    assert [e["event"] for e in n.sent] == ["up"]


def test_disabled_notifier_sends_nothing():
    n = Notifier("h", "http")
    n.event("down", "x")
    assert n.sent == []


def test_desktop_fallback_rings_bell_and_warns_once(monkeypatch, capsys):
    monkeypatch.setattr(notify, "desktop_notify", lambda title, message: False)
    n = Notifier("h", "tcp", desktop=True, clock=Clock())
    n.event("down")
    n.event("up")
    out = capsys.readouterr().out
    assert out.count("\a") == 2 and out.count("not available") == 1


def test_webhook_posts_every_event_and_warns_once_on_failure(monkeypatch, capsys):
    posted = []
    monkeypatch.setattr(notify, "post_webhook", lambda url, payload: posted.append((url, payload)))
    n = Notifier("h", "tcp", webhook="https://hooks.test/x", clock=Clock())
    n.event("down", "refused")
    n.flush()
    assert posted[0][0] == "https://hooks.test/x" and posted[0][1]["event"] == "down"

    def boom(url, payload):
        raise OSError("connection refused")

    monkeypatch.setattr(notify, "post_webhook", boom)
    n.event("up")
    n.event("down")
    n.flush()
    assert capsys.readouterr().out.count("Webhook delivery failed") == 1


def test_desktop_notify_passes_text_as_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(notify.shutil, "which", lambda name: f"/usr/bin/{name}")
    with patch.object(notify.sys, "platform", "darwin"):
        assert REAL_DESKTOP_NOTIFY("T", 'x" & $(rm -rf ~)')
    with patch.object(notify.sys, "platform", "linux"):
        assert REAL_DESKTOP_NOTIFY("T", "msg")
    with patch.object(notify.sys, "platform", "win32"):
        assert not REAL_DESKTOP_NOTIFY("T", "msg")
    # the text is an argv item, never part of the AppleScript source or a shell line
    assert calls[0][0] == "osascript" and calls[0][-2:] == ["T", 'x" & $(rm -rf ~)']
    assert calls[1] == ["notify-send", "--app-name=xping", "T", "msg"]


def test_watch_loop_feeds_the_notifier():
    clock = Clock()
    n = _notifier(clock)
    states = iter([True, False, False, True])

    def probe():
        try:
            ok = next(states)
        except StopIteration:
            raise KeyboardInterrupt from None
        return ok, 1.0 if ok else None, "connected" if ok else "refused"

    watch("db:5432", "tcp", probe, every=10, quiet=True, clock=clock, sleep=clock.sleep,
          notifier=n)
    assert [e["event"] for e in n.sent] == ["down", "up"]
    assert "after 20s" in n.sent[1]["text"]


def test_ping_watch_needs_three_losses(monkeypatch):
    from xping.diagnostics import ping as ping_diag

    rtts = iter([5.0, -1.0, -1.0, 6.0, -1.0, -1.0, -1.0, -1.0, 7.0])

    def fake_ping(host, seq, timeout=2.0):
        try:
            return next(rtts)
        except StopIteration:
            raise KeyboardInterrupt from None

    monkeypatch.setattr(ping_diag, "_icmp_ping", fake_ping)
    monkeypatch.setattr(ping_diag, "resolve", lambda host, family=None: "1.1.1.1")
    monkeypatch.setattr(ping_diag.time, "sleep", lambda s: None)
    monkeypatch.setattr(ping_diag.ping_view, "redraw_watch", lambda rtts, rows: 0)
    monkeypatch.setattr(ping_diag.ping_view, "print_summary", lambda result: None)
    n = _notifier()
    ping_diag.watch("1.1.1.1", interval=0, notifier=n)
    assert [e["event"] for e in n.sent] == ["down", "up"]  # 2 losses were not an outage
    assert "3 pings lost in a row" in n.sent[0]["text"]


def test_parser_and_usage():
    parser = build_parser()
    args = parser.parse_args(["http", "https://x.test", "--watch", "--webhook", "https://h.test/a"])
    assert args.webhook == "https://h.test/a" and not args.notify
    with pytest.raises(SystemExit):
        parser.parse_args(["tcp", "h", "22", "--watch", "--webhook", "ftp://h.test"])
    for argv in (["tcp", "h", "22", "--notify"], ["ping", "h", "--webhook", "http://h.test"]):
        with pytest.raises(UsageError, match="only works in watch mode"):
            getattr(commands, f"cmd_{argv[0]}")(parser.parse_args(argv))


def test_run_watch_passes_notifier(monkeypatch):
    seen = {}

    def fake_watch(target, check, probe, **kw):
        seen.update(kw, target=target)
        return None

    monkeypatch.setattr(commands, "watch", fake_watch)
    args = build_parser().parse_args(["tcp", "db", "5432", "--until-up", "--notify"])
    commands.cmd_tcp(args)
    assert isinstance(seen["notifier"], Notifier) and seen["notifier"].desktop
    assert seen["target"] == "db:5432"
    args = build_parser().parse_args(["tcp", "db", "5432", "--until-up"])
    commands.cmd_tcp(args)
    assert seen["notifier"] is None
