"""Combined host diagnostic bundle result."""

from dataclasses import dataclass, field

from ._export import model_to_dict
from .lookup import DnsResult
from .ping import PingResult
from .tcp import TcpResult
from .trace import Hop


@dataclass
class BundleResult:
    host: str
    lookup: DnsResult | None = None
    ping: PingResult | None = None
    trace: list[Hop] = field(default_factory=list)
    tcp: list[TcpResult] = field(default_factory=list)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
