"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _ignore_user_config(monkeypatch):
    """Never let the developer's own ~/.xping/config.toml change test results."""
    monkeypatch.setenv("XPING_CONFIG", "none")


@pytest.fixture(autouse=True)
def _ignore_user_check_file(monkeypatch, tmp_path_factory):
    """Never let the developer's own ~/.xping/checks.toml be read (or a
    new one be created) by `xping check` / `xping monitor` without a file."""
    from xping.diagnostics import check

    monkeypatch.setattr(check, "DEFAULT_DIR", tmp_path_factory.mktemp("xping-home") / ".xping")
