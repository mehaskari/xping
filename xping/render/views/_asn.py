"""Display helpers for AS (network operator) names."""


def short_name(name: str | None, width: int = 24) -> str:
    """Operator name trimmed for tables: "CLOUDFLARENET - Cloudflare, Inc., US" → "CLOUDFLARENET"."""
    if not name:
        return ""
    head = name.split(" - ", 1)[0].split(",", 1)[0].strip()
    return head if len(head) <= width else head[: width - 1] + "…"
