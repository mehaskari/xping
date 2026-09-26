"""
xping.diagnostics.notify — tell someone when a watched target goes down or
comes back (``--notify`` / ``--webhook`` in watch mode).

Desktop notifications use the OS's own tool, with the text passed as
arguments, never through a shell:

  macOS    osascript (Notification Center)
  Linux    notify-send (libnotify)
  other    a terminal bell

Webhooks get one JSON POST per event. The body carries both ``text``
(Slack, Mattermost, Rocket.Chat, Google Chat) and ``content`` (Discord)
plus structured fields for anything else. Sending happens on a background
thread so a slow endpoint never delays the next check; a failure is
reported once and does not stop watching.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

from xping.diagnostics.sslctx import secure_context
from xping.render.errors import warn

WEBHOOK_TIMEOUT = 5.0


def valid_webhook(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def desktop_notify(title: str, message: str) -> bool:
    """Show a desktop notification. False when no notifier is available."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        cmd = [
            "osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 2 of argv) with title (item 1 of argv)",
            "-e",
            "end run",
            title,
            message,
        ]
    elif sys.platform.startswith("linux") and shutil.which("notify-send"):
        cmd = ["notify-send", "--app-name=xping", title, message]
    else:
        return False
    try:
        subprocess.run(cmd, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def post_webhook(url: str, payload: dict) -> None:
    """POST *payload* as JSON; raises on network or HTTP errors."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "xping/notify"},
    )
    context = secure_context() if url.lower().startswith("https:") else None
    with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT, context=context) as resp:
        resp.read(1024)


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


class Notifier:
    """Sends "down" / "up" events for one watched target."""

    def __init__(
        self,
        target: str,
        check: str,
        desktop: bool = False,
        webhook: str | None = None,
        clock=time.time,
    ):
        self.target = target
        self.check = check
        self.desktop = desktop
        self.webhook = webhook
        self.clock = clock
        self.down_since: float | None = None
        self.sent: list[dict] = []  # every event, for tests and summaries
        self._threads: list[threading.Thread] = []
        self._warned: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self.desktop or bool(self.webhook)

    # -- decisions --------------------------------------------------------

    def observe(
        self,
        ok: bool,
        previous_ok: bool | None,
        detail: str = "",
        latency=None,
        final: bool = False,
    ) -> None:
        """Feed one check result. Events fire on every up/down change; the
        first check only sets the baseline, except when it ends an
        --until-up wait (*final*), which always announces "up"."""
        now = self.clock()
        if previous_ok is None:
            if not ok:
                self.down_since = now
            elif final:
                self.event("up", detail, latency)
            return
        if ok == previous_ok:
            return
        if ok:
            self.event("up", detail, latency)
            self.down_since = None
        else:
            self.down_since = now
            self.event("down", detail, latency)

    # -- delivery ---------------------------------------------------------

    def message(self, kind: str, detail: str) -> str:
        if kind == "down":
            text = f"{self.target} ({self.check}) is DOWN"
        else:
            text = f"{self.target} ({self.check}) is UP"
            if self.down_since is not None:
                text += f" again after {_duration(self.clock() - self.down_since)}"
        return f"{text} — {detail}" if detail else text

    def event(self, kind: str, detail: str = "", latency=None) -> None:
        if not self.enabled:
            return
        text = self.message(kind, detail)
        payload = {
            "source": "xping",
            "event": kind,
            "target": self.target,
            "check": self.check,
            "detail": detail,
            "latency_ms": round(latency, 3) if isinstance(latency, int | float) else None,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "machine": socket.gethostname(),
            "text": f"{'🔴' if kind == 'down' else '🟢'} xping: {text}",
        }
        payload["content"] = payload["text"]
        self.sent.append(payload)
        if self.desktop and not desktop_notify(f"xping — {kind.upper()}", text):
            print("\a", end="", flush=True)  # no notifier: at least ring the bell
            self._warn_once(
                "desktop",
                "Desktop notifications are not available here (install notify-send);"
                " ringing the terminal bell instead.",
            )
        if self.webhook:
            thread = threading.Thread(target=self._send, args=(payload,), daemon=True)
            thread.start()
            self._threads.append(thread)

    def _send(self, payload: dict) -> None:
        try:
            post_webhook(self.webhook, payload)
        except Exception as exc:
            self._warn_once("webhook", f"Webhook delivery failed: {exc}")

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            warn(message)

    def flush(self, timeout: float = WEBHOOK_TIMEOUT + 1) -> None:
        """Wait for pending webhook posts (called before exiting)."""
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))
