"""Compatibility shim — use xping.diagnostics.deps."""

from xping.diagnostics.deps import (
    check_all,
    get_distro,
    install_cmd,
    is_available,
    print_deps_status,
    require,
    warn_missing,
)

__all__ = [
    "check_all",
    "get_distro",
    "install_cmd",
    "is_available",
    "print_deps_status",
    "require",
    "warn_missing",
]
