"""Markdown export for diagnostic results."""

from __future__ import annotations

from typing import Any

from .serialize import to_dict


def export_markdown(result: Any, *, title: str = "XPing Result") -> str:
    """Serialize a diagnostic result to Markdown."""
    if isinstance(result, list):
        lines = [f"# {title}", ""]
        for index, item in enumerate(result, start=1):
            lines.append(f"## Item {index}")
            lines.extend(_markdown_fields(to_dict(item)))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    data = result.to_dict() if hasattr(result, "to_dict") else to_dict(result)
    lines = [f"# {title}", ""]
    lines.extend(_markdown_fields(data))
    return "\n".join(lines).rstrip() + "\n"


def _markdown_fields(data: dict[str, Any]) -> list[str]:
    lines = ["| Field | Value |", "| --- | --- |"]
    for key, value in sorted(data.items()):
        lines.append(f"| {key} | {_md_cell(value)} |")
    return lines


def _md_cell(value: Any) -> str:
    text = repr(value) if isinstance(value, (list, dict, tuple)) else str(value)
    return text.replace("|", "\\|").replace("\n", " ")
