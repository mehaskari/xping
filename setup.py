"""Minimal setup.py shim for Debian/Ubuntu packaging tools (debuild/pybuild).
All real metadata lives in pyproject.toml — this file exists only so that
`pybuild`, which predates PEP 517/518 pyproject-only builds on some
distributions, has something to invoke.
"""
from setuptools import setup

setup()
