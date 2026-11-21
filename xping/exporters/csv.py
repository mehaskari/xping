"""CSV export for diagnostic results.

Results with natural rows (ping replies, trace hops, scanned ports, …)
export one row per item with a header line, ready for a spreadsheet.
Results whose payload is a set of fields (TLS, WHOIS, HTTP, health, …)
export ``field,value`` pairs.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from .tables import cell, sections_for, summary_for

# A spreadsheet runs a cell that starts with one of these as a formula
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value: Any) -> str:
    """cell(), with text that a spreadsheet would treat as a formula made
    literal: DNS records, headers and banners come from remote servers."""
    text = cell(value)
    if isinstance(value, str) and text.startswith(_FORMULA_START):
        try:
            float(text)  # "-12.5" is a number, not a formula
        except ValueError:
            return "'" + text
    return text


def export_csv(result: Any) -> str:
    """Serialize a diagnostic result to CSV text."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    sections = sections_for(result)
    if sections and sections[0].primary:
        primary = sections[0]
        writer.writerow(primary.columns)
        writer.writerows([_csv_cell(v) for v in row] for row in primary.rows)
        return buf.getvalue()

    writer.writerow(["field", "value"])
    if isinstance(result, list):
        return buf.getvalue()
    for key, value in summary_for(result):
        writer.writerow([key, _csv_cell(value)])
    return buf.getvalue()
