"""Shared TLS client context for every HTTPS/TLS-speaking diagnostic."""

import ssl

import certifi


def secure_context() -> ssl.SSLContext:
    """Return a verifying client context that refuses anything below TLS 1.2.

    The system CA store is loaded first, then certifi's bundle on top of it —
    many Python builds (Homebrew, pyenv, python.org on macOS) ship without a
    usable system store, so certifi is what makes verification work there.
    """
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_verify_locations(certifi.where())
    return ctx
