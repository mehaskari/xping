"""JSON export for diagnostic results."""

from __future__ import annotations

import json
from typing import Any

from .serialize import to_dict


def export_json(result: Any, *, indent: int = 2) -> str:
    """Serialize a diagnostic result (or bundle) to JSON."""
    if isinstance(result, list):
        payload = [to_dict(item) for item in result]
    elif hasattr(result, "to_dict"):
        payload = result.to_dict()
    else:
        payload = to_dict(result)
    return json.dumps(payload, indent=indent)
