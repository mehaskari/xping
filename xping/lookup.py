"""Compatibility shim — use xping.diagnostics.lookup."""
from xping.models.lookup import DnsResult
from xping.diagnostics.lookup import (
    lookup,
    _parse_dig_a,
    _parse_dig_aaaa,
    _parse_dig_cname,
    _parse_dig_mx,
    _parse_dig_ns,
    _parse_dig_txt,
    _socket_resolve,
    _raw_query,
)

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
    "_raw_query",
]
