"""Watch-mode render view."""

import time

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from ..latency import latency_color
from ..tables import print_table


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def print_sample(sample, previous, result) -> None:
    if previous is not None and previous.ok != sample.ok:
        if sample.ok:
            earlier = result.samples[:-1]
            last_up = next((i for i in range(len(earlier) - 1, -1, -1) if earlier[i].ok), None)
            if last_up is None:
                down = sample.ts - earlier[0].ts
                print(c(f"  ▲ UP after {_duration(down)}", BRAND_MINT, BOLD))
            else:
                down = sample.ts - earlier[last_up + 1].ts
                print(c(f"  ▲ UP again after {_duration(down)} of downtime", BRAND_MINT, BOLD))
        else:
            print(c("  ▼ DOWN", BRAND_ROSE, BOLD))
    stamp = c(time.strftime("%H:%M:%S", time.localtime(sample.ts)), DIM)
    seq = c(f"#{sample.seq:<4}", BRAND_SLATE)
    state = c("✔ UP  ", BRAND_MINT, BOLD) if sample.ok else c("✘ DOWN", BRAND_ROSE, BOLD)
    latency = (
        latency_color(sample.latency_ms)
        if sample.latency_ms and sample.latency_ms >= 0
        else c("—", DIM)
    )
    print(f"  {stamp}  {seq} {state}  {latency}  {c(sample.detail, DIM)}")


def print_up(result) -> None:
    waited = result.samples[-1].ts - result.samples[0].ts
    print()
    print(
        c(f"  ✔ {result.target} is up", BRAND_MINT, BOLD)
        + c(f"  (waited {_duration(waited)}, {result.checks} checks)", DIM)
    )
    print()


def print_summary(result) -> None:
    if not result.samples:
        return
    print()
    latencies = [
        s.latency_ms
        for s in result.samples
        if s.ok and s.latency_ms is not None and s.latency_ms >= 0
    ]
    up_color = (
        BRAND_MINT if result.up_pct == 100 else BRAND_AMBER if result.up_pct >= 90 else BRAND_ROSE
    )
    rows = [
        ["Checks", c(str(result.checks), BWHITE)],
        ["Up", c(f"{result.up_pct:.1f}%", up_color)],
        ["State changes", str(result.transitions)],
        ["Longest outage", _duration(result.longest_outage_s) if result.longest_outage_s else "—"],
        ["Avg latency (up)", latency_color(sum(latencies) / len(latencies)) if latencies else "—"],
        [
            "Final state",
            c("UP", BRAND_MINT, BOLD) if result.last_ok else c("DOWN", BRAND_ROSE, BOLD),
        ],
    ]
    print_table(["Metric", "Value"], rows)
    print()
