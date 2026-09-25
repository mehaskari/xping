"""
xping.deps — Runtime system dependency checker.

Detects missing external binaries (ping, traceroute, dig) and tells
the user exactly how to install them on their distro.
"""

import platform
import shutil

from xping.render import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BWHITE, DIM, c
from xping.render.errors import missing_tool, warn

# ── Distro detection ──────────────────────────────────────────────────────────


def _detect_distro() -> str:
    """Return a short platform family string."""
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    if system == "windows":
        return "windows"

    # /etc/os-release is the modern standard (systemd distros)
    try:
        with open("/etc/os-release") as f:
            text = f.read().lower()
        if any(k in text for k in ("ubuntu", "debian", "mint", "pop", "kali", "raspbian")):
            return "debian"
        if any(k in text for k in ("fedora", "rhel", "centos", "rocky", "alma", "oracle")):
            return "rhel"
        if "arch" in text or "manjaro" in text or "endeavour" in text:
            return "arch"
        if "opensuse" in text or "suse" in text:
            return "suse"
        if "alpine" in text:
            return "alpine"
        if "void" in text:
            return "void"
    except FileNotFoundError:
        pass  # no os-release (older/minimal systems) — probe package managers below

    # Fallback: check for package manager binaries
    for mgr, family in (
        ("apt-get", "debian"),
        ("dnf", "rhel"),
        ("yum", "rhel"),
        ("pacman", "arch"),
        ("zypper", "suse"),
        ("apk", "alpine"),
        ("xbps-install", "void"),
    ):
        if shutil.which(mgr):
            return family

    return "unknown"


# ── Install instructions per package per distro ───────────────────────────────

_INSTALL_CMDS: dict[str, dict[str, str]] = {
    "ping": {
        "debian": "sudo apt install iputils-ping",
        "rhel": "sudo dnf install iputils",
        "arch": "sudo pacman -S iputils",
        "suse": "sudo zypper install iputils",
        "alpine": "sudo apk add iputils",
        "void": "sudo xbps-install iputils",
        "darwin": "brew install iputils (usually pre-installed on macOS)",
        "windows": "ping is built into Windows",
        "unknown": "install iputils (provides ping)",
    },
    "traceroute": {
        "debian": "sudo apt install traceroute",
        "rhel": "sudo dnf install traceroute",
        "arch": "sudo pacman -S traceroute",
        "suse": "sudo zypper install traceroute",
        "alpine": "sudo apk add traceroute",
        "void": "sudo xbps-install traceroute",
        "darwin": "brew install traceroute (or use built-in network tools)",
        "windows": "tracert is built into Windows",
        "unknown": "install traceroute",
    },
    "dig": {
        "debian": "sudo apt install dnsutils",
        "rhel": "sudo dnf install bind-utils",
        "arch": "sudo pacman -S bind",
        "suse": "sudo zypper install bind-utils",
        "alpine": "sudo apk add bind-tools",
        "void": "sudo xbps-install bind-utils",
        "darwin": "brew install bind",
        "windows": "install BIND tools or use WSL for dig",
        "unknown": "install bind-utils / dnsutils (provides dig)",
    },
}

# Cache distro detection (called multiple times potentially)
_DISTRO: str | None = None


def get_distro() -> str:
    global _DISTRO
    if _DISTRO is None:
        _DISTRO = _detect_distro()
    return _DISTRO


def install_cmd(binary: str) -> str:
    """Return the install command for *binary* on the current distro."""
    distro = get_distro()
    return _INSTALL_CMDS.get(binary, {}).get(
        distro, _INSTALL_CMDS.get(binary, {}).get("unknown", f"install {binary}")
    )


def is_available(binary: str) -> bool:
    if binary == "traceroute":
        from xping.diagnostics.platform_cmds import trace_tool

        return trace_tool() is not None
    return shutil.which(binary) is not None


# ── Check helpers used by subcommands ─────────────────────────────────────────


def require(binary: str, purpose: str) -> bool:
    """
    Check if *binary* is available. If not, print a helpful error and return False.
    Callers should abort their operation when this returns False.
    """
    if is_available(binary):
        return True

    missing_tool(binary, purpose, install_cmd(binary))
    return False


def warn_missing(binary: str, fallback_desc: str) -> None:
    """
    Print a soft warning that *binary* is missing but a fallback is in use.
    Does not abort — the caller continues with degraded functionality.
    """
    warn(
        f"'{binary}' not found — {fallback_desc}",
        hint=f"For full functionality: {install_cmd(binary)}",
    )


def check_all() -> dict[str, bool]:
    """Return availability of all external tools xping uses."""
    tools = {
        "ping": is_available("ping"),
        "traceroute": is_available("traceroute"),
        "dig": is_available("dig"),
    }
    return tools


def print_deps_status() -> None:
    """Pretty-print a dependency status table (used by `xping deps`)."""
    from xping.render import kv, print_table, section_header

    print(section_header("DEPENDENCY CHECK", "◈"))
    print(kv("Distro family", c(get_distro(), BWHITE)))
    print(kv("Python", c(platform.python_version(), BWHITE)))
    print()

    rows = []
    for binary, ok in check_all().items():
        status = c(" ✔ found   ", BRAND_MINT, BOLD) if ok else c(" ✘ missing ", BRAND_ROSE, BOLD)
        cmd = c("—", DIM) if ok else c(install_cmd(binary), BRAND_AMBER)
        rows.append([c(binary, BWHITE), status, cmd])

    print_table(["Tool", "Status", "Install command"], rows)

    # Native ICMP capability (unprivileged ping sockets, or raw with root)
    import socket as _socket

    from xping.diagnostics.icmp import socket_mode

    labels = {
        "dgram": c(" ✔ unprivileged ICMP sockets — no root needed", BRAND_MINT),
        "raw": c(" ✔ raw sockets (running as root or cap_net_raw)", BRAND_MINT),
        None: c(" ℹ  unavailable — using system ping/traceroute fallback", BRAND_AMBER),
    }
    icmp_v4 = labels[socket_mode(_socket.AF_INET)]
    icmp_v6 = labels[socket_mode(_socket.AF_INET6)]

    print()
    print(kv("Native ICMP (v4)", icmp_v4))
    print(kv("Native ICMP (v6)", icmp_v6))
    print()
