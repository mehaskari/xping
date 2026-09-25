"""CLI-level exceptions."""


class UsageError(ValueError):
    """Invalid combination of arguments — reported like argparse errors (exit 2)."""
