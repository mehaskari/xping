"""Compatibility shim — use xping.diagnostics.lookup."""

from xping.diagnostics.lookup import (
    _parse_dig_a,
    _parse_dig_aaaa,
    _parse_dig_cname,
    _parse_dig_mx,
    _parse_dig_ns,
    _parse_dig_txt,
    _socket_resolve,
    lookup,
)
from xping.models.lookup import DnsResult

__all__ = [
    "DnsResult",
    "lookup",
    "_parse_dig_a",
    "_parse_dig_aaaa",
    "_parse_dig_cname",
    "_parse_dig_mx",
    "_parse_dig_ns",
    "_parse_dig_txt",
    "_socket_resolve",
]
