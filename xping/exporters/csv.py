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


def export_csv(result: Any) -> str:
    """Serialize a diagnostic result to CSV text."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    sections = sections_for(result)
    if sections and sections[0].primary:
        primary = sections[0]
        writer.writerow(primary.columns)
        writer.writerows([cell(v) for v in row] for row in primary.rows)
        return buf.getvalue()

    writer.writerow(["field", "value"])
    if isinstance(result, list):
        return buf.getvalue()
    for key, value in summary_for(result):
        writer.writerow([key, cell(value)])
    return buf.getvalue()
