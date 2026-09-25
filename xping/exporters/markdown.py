"""Markdown export for diagnostic results: a summary table of the scalar
fields followed by one table per section (hops, ports, records, …)."""

from __future__ import annotations

from typing import Any

from .tables import Section, cell, sections_for, summary_for


def export_markdown(result: Any, *, title: str = "XPing Result") -> str:
    """Serialize a diagnostic result to Markdown."""
    lines = [f"# {title}", ""]
    summary = summary_for(result)
    if summary:
        lines += _table(["Field", "Value"], [[k, v] for k, v in summary])
        lines.append("")
    for section in sections_for(result):
        lines += [f"## {section.title}", ""]
        lines += _section(section)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _section(section: Section) -> list[str]:
    if not section.rows:
        return ["_none_"]
    return _table(section.columns, section.rows)


def _table(columns: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    out += ["| " + " | ".join(_md(v) for v in row) + " |" for row in rows]
    return out


def _md(value: Any) -> str:
    return cell(value).replace("|", "\\|").replace("\n", " ")
