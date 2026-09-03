"""Actionable error and warning output."""

import sys

from .ansi import BOLD, BRAND_AMBER, BRAND_ROSE, BRAND_SLATE, c


def error(message: str, *, hint: str | None = None, file=None) -> None:
    """Print a user-facing error message."""
    if file is None:
        file = sys.stderr
    print(c(f"\n  ✘  {message}", BRAND_ROSE, BOLD), file=file)
    if hint:
        print(c(f"  {hint}", BRAND_SLATE), file=file)


def warn(message: str, *, hint: str | None = None) -> None:
    """Print a non-fatal warning."""
    print(c(f"  ℹ  {message}", BRAND_AMBER))
    if hint:
        print(c(f"     {hint}", BRAND_SLATE))


def resolve_error(host: str, exc: Exception | None = None) -> None:
    """Report a DNS resolution failure."""
    if exc is None:
        error(f"Cannot resolve '{host}'")
        return
    error(f"Cannot resolve '{host}': {exc}")


def missing_tool(binary: str, purpose: str, install: str) -> None:
    """Report a missing external binary with install guidance."""
    error(
        f"'{binary}' not found — needed for {purpose}",
        hint=f"Install it: {install}",
    )
