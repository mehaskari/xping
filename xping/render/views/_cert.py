"""Short, readable certificate names for the tls and smtp views."""

import re

_FIELD = re.compile(r"(\w+)=(.*?)(?=, \w+=|$)")


def cert_name(dn: str | None) -> str:
    """ "countryName=US, organizationName=Google Trust Services, commonName=WE2"
    -> "Google Trust Services (WE2)". The full name stays in --json."""
    if not dn:
        return "—"
    fields = dict(_FIELD.findall(dn))
    org, cn = fields.get("organizationName"), fields.get("commonName")
    if org and cn and cn != org and org not in cn:
        return f"{org} ({cn})"
    return cn or org or dn
