"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _ignore_user_config(monkeypatch):
    """Never let the developer's own ~/.xping/config.toml change test results."""
    monkeypatch.setenv("XPING_CONFIG", "none")
