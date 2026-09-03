"""CLI entry point for python -m xping."""

from xping.cli.main import main
from xping.cli.parser import build_parser

__all__ = ["main", "build_parser"]

if __name__ == "__main__":
    main()
