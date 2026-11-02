#!/usr/bin/env python3
"""
Check contrib/grafana/xping-dashboard.json against a live Prometheus that
scrapes `xping monitor --metrics`: every panel's query, with Grafana's
variables filled in, must return data. Used by the "Grafana dashboard"
workflow; also handy by hand:

  python3 scripts/check_dashboard.py http://localhost:9090
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "contrib/grafana/xping-dashboard.json"
# what Grafana substitutes before a query reaches Prometheus
VARIABLES = {"$check": ".*", "$__range": "5m", "$__rate_interval": "2m"}


def query(prometheus: str, expr: str) -> list:
    url = f"{prometheus.rstrip('/')}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=10) as resp:
        body = json.load(resp)
    if body.get("status") != "success":
        raise RuntimeError(f"{expr}: {body}")
    return body["data"]["result"]


def main(argv: list[str]) -> int:
    prometheus = argv[1] if len(argv) > 1 else "http://localhost:9090"
    dashboard = json.loads(DASHBOARD.read_text())
    failed = 0
    for panel in dashboard["panels"]:
        for target in panel["targets"]:
            expr = target["expr"]
            for name, value in VARIABLES.items():
                expr = expr.replace(name, value)
            try:
                series = query(prometheus, expr)
            except Exception as exc:  # noqa: BLE001 (report and go on)
                print(f"FAIL  {panel['title']}: {exc}")
                failed += 1
                continue
            status = "ok  " if series else "FAIL"
            failed += not series
            print(f"{status}  {panel['title']}: {len(series)} series  ({expr})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
