"""Saved-results history render view (xping history)."""

import time

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BRAND_SLATE, BWHITE, DIM, c
from ..latency import spark_bar
from ..layout import kv, section_header
from ..tables import print_table


def _when(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _value(value, unit: str) -> str:
    if value is None:
        return c("—", DIM)
    text = f"{value:.0f}" if unit in ("", "dBm", "dB") else f"{value:.1f}"
    return f"{text} {unit}".strip()


def print_list(result) -> None:
    print(section_header("HISTORY", "◷"))
    print()
    if not result.entries:
        print(c("  Nothing saved yet. Add --save to a check, e.g.:", BWHITE))
        print(c("    xping ping example.net --save", BRAND_SLATE))
        print(c("  or put  save = true  under [defaults] in ~/.xping/config.toml", DIM))
        print()
        return
    rows = [
        [c(e.command, BWHITE, BOLD), e.target, str(e.runs), _when(e.first), _when(e.last)]
        for e in result.entries
    ]
    print_table(["Command", "Target", "Runs", "First", "Last"], rows)
    print()
    print(c("  Show one:  xping history COMMAND TARGET", DIM))
    print()


def print_result(result) -> None:
    print(section_header(f"HISTORY  {result.command}  {result.target}", "◷"))
    print()
    if result.error:
        print(c(f"  ✘ {result.error}", BRAND_ROSE, BOLD))
        print()
        return
    rows = []
    for run in result.runs[-30:]:
        state = c("✔", BRAND_MINT, BOLD) if run.ok else c("✘", BRAND_ROSE, BOLD)
        rows.append(
            [_when(run.ts), state]
            + [_value(run.values.get(m), result.units.get(m, "")) for m in result.metrics]
        )
    print_table(["Time", "OK"] + result.metrics, rows)
    if len(result.runs) > 30:
        print(c(f"  (last 30 of {len(result.runs)} runs; --json has them all)", DIM))
    print()
    if result.metrics:
        headline = result.metrics[0]
        series = [r.values.get(headline) for r in result.runs]
        values = [v if v is not None else -1.0 for v in series]
        if any(v is not None for v in series):
            print(kv(f"{headline} trend", spark_bar(values, width=40)))
    ok = result.ok_pct
    if ok is not None:
        color = BRAND_MINT if ok == 100 else BRAND_AMBER if ok >= 90 else BRAND_ROSE
        print(kv("Passed", c(f"{ok:.0f}% of {len(result.runs)} runs", color)))
    if result.latest_vs_median_pct is not None:
        pct = result.latest_vs_median_pct
        unit = result.units.get(result.metrics[0], "")
        usual = _value(result.median, unit)
        if abs(pct) < 10:
            text, color = f"about as usual (median {usual})", BRAND_MINT
        else:
            word = "above" if pct > 0 else "below"
            text, color = f"{abs(pct):.0f}% {word} its median ({usual})", BRAND_AMBER
        print(kv("Latest run", c(f"{result.metrics[0]} {text}", color)))
    print()
