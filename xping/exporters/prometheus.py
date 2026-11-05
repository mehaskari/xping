"""
xping.exporters.prometheus — ``xping monitor --metrics``: the monitored
checks as Prometheus metrics.

``render()`` writes the text exposition format (version 0.0.4, which
Prometheus, VictoriaMetrics, the Grafana agent and OpenMetrics scrapers all
read); ``MetricsServer`` serves it at ``/metrics`` (and the status page's
paths, see xping.exporters.status_page) from a background thread with the
standard library's HTTP server, so monitor keeps its own loop and no
dependency is needed. It listens on 127.0.0.1 unless told otherwise.
"""

from __future__ import annotations

import math
import socket
import sys
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from xping import __version__

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
DEFAULT_HOST = "127.0.0.1"
# the pages are ours: inline CSS only, and browsers must not guess types
_SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"),
)


class ListenError(ValueError):
    """A --metrics address that cannot be parsed or bound."""


def parse_listen(text: str) -> tuple[str, int]:
    """``PORT``, ``:PORT``, ``HOST:PORT`` or ``[IPv6]:PORT`` → (host, port);
    without a host, only this machine can scrape (127.0.0.1)."""
    text = text.strip()
    host, sep, port_text = text.rpartition(":")
    if not sep:
        host, port_text = "", text
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    elif ":" in host:
        raise ListenError(f"'{text}': put an IPv6 address in brackets, e.g. [::1]:9101")
    try:
        port = int(port_text)
    except ValueError:
        raise ListenError(f"'{text}' is not [HOST:]PORT, e.g. :9101 or 0.0.0.0:9101") from None
    if not 1 <= port <= 65535:
        raise ListenError(f"port {port} is out of range (1-65535)")
    return host or DEFAULT_HOST, port


def format_listen(host: str, port: int) -> str:
    """The inverse of parse_listen (brackets around an IPv6 host)."""
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(**labels: str) -> str:
    return "{" + ",".join(f'{key}="{_escape(str(val))}"' for key, val in labels.items()) + "}"


def _number(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    return repr(int(value)) if float(value).is_integer() else repr(float(value))


# name, type, help — in the order they are written
_FAMILIES = (
    ("xping_check_up", "gauge", "Confirmed state: 1 up, 0 down (after fail_after / recover_after)"),
    ("xping_check_last_run_ok", "gauge", "Result of the latest run: 1 passed, 0 failed"),
    ("xping_check_value", "gauge", "Latest value of the headline metric (see metric and unit)"),
    ("xping_check_latency_seconds", "gauge", "Latest latency, for checks that measure a time"),
    ("xping_check_runs_total", "counter", "Runs of the check since monitor started"),
    ("xping_check_failures_total", "counter", "Failed runs since monitor started"),
    ("xping_check_outages_total", "counter", "Confirmed outages since monitor started"),
    ("xping_check_last_run_timestamp_seconds", "gauge", "Unix time the latest run finished"),
    ("xping_check_state_change_timestamp_seconds", "gauge", "Unix time the confirmed state began"),
    ("xping_check_interval_seconds", "gauge", "Seconds between runs of the check"),
    ("xping_monitor_start_time_seconds", "gauge", "Unix time this monitor started"),
    ("xping_build_info", "gauge", "xping version, always 1"),
)


def render(result) -> str:
    """The monitor's checks (a MonitorResult) in the text exposition format."""
    series: dict[str, list[str]] = {name: [] for name, _kind, _help in _FAMILIES}
    for check in result.checks:
        base = {"check": check.name, "type": check.type, "target": check.target}
        labels = _labels(**base)

        def add(name: str, value: float, labels: str = labels) -> None:
            series[name].append(f"{name}{labels} {_number(value)}")

        if check.up is not None:
            add("xping_check_up", 1 if check.up else 0)
        if check.last_ok is not None:
            add("xping_check_last_run_ok", 1 if check.last_ok else 0)
        if check.latest is not None:
            metric_labels = _labels(**base, metric=check.metric or "", unit=check.unit)
            add("xping_check_value", check.latest, metric_labels)
            if check.unit == "ms":
                add("xping_check_latency_seconds", check.latest / 1000)
        add("xping_check_runs_total", check.checks)
        add("xping_check_failures_total", check.failures)
        add("xping_check_outages_total", check.outages)
        if check.samples:
            add("xping_check_last_run_timestamp_seconds", check.samples[-1].ts)
        if check.since is not None:
            add("xping_check_state_change_timestamp_seconds", check.since)
        add("xping_check_interval_seconds", check.every)
    series["xping_monitor_start_time_seconds"].append(
        f"xping_monitor_start_time_seconds {_number(result.started)}"
    )
    series["xping_build_info"].append(f"xping_build_info{_labels(version=__version__)} 1")
    out = []
    for name, kind, help_text in _FAMILIES:
        if series[name]:
            out.append(f"# HELP {name} {help_text}")
            out.append(f"# TYPE {name} {kind}")
            out.extend(series[name])
    return "\n".join(out) + "\n"


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def _respond(self, *, head: bool) -> None:
        path = self.path.split("?", 1)[0]
        page = self.server.pages.get(path)
        if page is not None:
            kind, produce = page
            body, status = produce().encode(), 200
        elif path == "/":
            body = b'<html><body><a href="/metrics">xping metrics</a></body></html>\n'
            status, kind = 200, "text/html; charset=utf-8"
        else:
            body, status, kind = b"not found\n", 404, "text/plain; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for name, value in _SECURITY_HEADERS:
            self.send_header(name, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
        self._respond(head=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._respond(head=True)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # scrapes every few seconds would flood the monitor's output


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    pages: dict[str, tuple[str, Callable[[], str]]]
    # SO_REUSEADDR on Windows lets a second server bind a port that is in
    # use, so two monitors would share one --metrics port; ask for the port
    # exclusively there instead (elsewhere it only allows a quick restart)
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Server6(_Server):
    address_family = socket.AF_INET6


class MetricsServer:
    """Serves ``produce()`` at /metrics, and *pages* (path → content type,
    function giving the body) next to it, until stop()."""

    def __init__(
        self,
        host: str,
        port: int,
        produce: Callable[[], str],
        pages: dict[str, tuple[str, Callable[[], str]]] | None = None,
    ):
        server_class = _Server6 if ":" in host else _Server
        try:
            self._server = server_class((host, port), _Handler)
        except OSError as exc:
            raise ListenError(
                f"cannot listen on {format_listen(host, port)}: {exc.strerror or exc}"
            ) from exc
        self._server.pages = {"/metrics": (CONTENT_TYPE, produce), **(pages or {})}
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="xping-metrics", daemon=True
        )

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> MetricsServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
