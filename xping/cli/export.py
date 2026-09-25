"""Output-mode helpers for CLI commands."""

from __future__ import annotations

import argparse

from xping.exporters.csv import export_csv
from xping.exporters.json import export_json
from xping.exporters.markdown import export_markdown


def export_requested(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "json", False)
        or getattr(args, "csv", False)
        or getattr(args, "markdown", False)
    )


def output_suppressed(args: argparse.Namespace) -> bool:
    """True when the interactive rendering must be skipped: an export format
    was requested, or --quiet asked for no output at all (exit code only)."""
    return export_requested(args) or bool(getattr(args, "quiet", False))


def emit_export(result, args: argparse.Namespace) -> None:
    """Print *result* in the requested export format; no-op otherwise."""
    if getattr(args, "json", False):
        print(export_json(result))
    elif getattr(args, "csv", False):
        print(export_csv(result))
    elif getattr(args, "markdown", False):
        print(export_markdown(result))
