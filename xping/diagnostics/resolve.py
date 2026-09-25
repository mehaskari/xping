"""Host resolution with IPv4/IPv6 selection (-4 / -6)."""

from __future__ import annotations

import ipaddress
import socket


def ip_version(ip: str) -> int:
    """Return 4 or 6 for an IP literal (raises ValueError otherwise)."""
    return ipaddress.ip_address(ip.split("%", 1)[0]).version


def is_ipv6(ip: str) -> bool:
    try:
        return ip_version(ip) == 6
    except ValueError:
        return False


def family_of(args) -> int | None:
    """Map the -4/-6 CLI flags on *args* to a socket address family."""
    if getattr(args, "ipv6", False):
        return socket.AF_INET6
    if getattr(args, "ipv4", False):
        return socket.AF_INET
    return None


def resolve(host: str, family: int | None = None) -> str:
    """Resolve *host* to one IP address.

    Without *family*, IPv4 is preferred (matching every earlier xping
    release) and IPv6 is used only when the name has no IPv4 address, so
    IPv6-only hosts now work instead of failing to resolve. ``AF_INET`` /
    ``AF_INET6`` force one family. Raises ``socket.gaierror`` when nothing
    suitable exists.
    """
    try:
        version = ip_version(host)
    except ValueError:
        version = None
    if version is not None:
        if (family == socket.AF_INET and version == 6) or (
            family == socket.AF_INET6 and version == 4
        ):
            raise socket.gaierror(f"{host} is an IPv{version} address")
        return host

    if family != socket.AF_INET6:
        try:
            return socket.gethostbyname(host)
        except socket.gaierror:
            if family == socket.AF_INET:
                raise
    infos = socket.getaddrinfo(host, None, socket.AF_INET6, socket.SOCK_STREAM)
    if not infos:
        raise socket.gaierror(f"no IPv6 address found for {host}")
    return infos[0][4][0]
