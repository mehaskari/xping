"""Export output helpers for CLI commands."""

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


def emit_export(result, args: argparse.Namespace) -> None:
    if args.json:
        print(export_json(result))
    elif args.csv:
        print(export_csv(result))
    elif args.markdown:
        print(export_markdown(result))
