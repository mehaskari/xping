"""WHOIS lookup result model."""

from dataclasses import dataclass, field

from ._export import model_to_dict


@dataclass
class WhoisResult:
    domain: str
    whois_server: str | None = None
    registrar: str | None = None
    creation_date: str | None = None
    expiration_date: str | None = None
    updated_date: str | None = None
    status: list[str] = field(default_factory=list)
    name_servers: list[str] = field(default_factory=list)
    raw_text: str | None = None
    error: str | None = None

    @property
    def found(self) -> bool:
        return self.error is None and bool(self.raw_text)

    def to_dict(self, *, include_computed: bool = True) -> dict:
        return model_to_dict(self, include_computed=include_computed)
