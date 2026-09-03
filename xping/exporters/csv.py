"""CSV export for diagnostic results."""

from __future__ import annotations

import csv
import io
from typing import Any

from .serialize import to_dict


def export_csv(result: Any) -> str:
    """Serialize a diagnostic result to CSV text."""
    if isinstance(result, list):
        rows = [to_dict(item) for item in result]
        if not rows:
            return ""
        fieldnames = sorted({key for row in rows for key in row})
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()

    data = result.to_dict() if hasattr(result, "to_dict") else to_dict(result)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["field", "value"])
    for key, value in sorted(data.items()):
        writer.writerow([key, _csv_cell(value)])
    return buf.getvalue()


def _csv_cell(value: Any) -> str:
    if isinstance(value, (list, dict, tuple)):
        return repr(value)
    return str(value)
