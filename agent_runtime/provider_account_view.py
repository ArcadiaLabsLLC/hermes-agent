"""Pure account display projection; unknown fields stay null."""
from __future__ import annotations

__layer__ = "policy"


def account_text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def account_view(provider: str, snapshot) -> dict:
    """Opaque IDs and provider labels cannot supply an email or organisation."""
    raw = getattr(snapshot, "raw", None)
    reported = raw.get("account") if isinstance(raw, dict) else None
    reported = reported if isinstance(reported, dict) else {}
    return {"email": account_text(reported.get("email")),
            "organisation": account_text(reported.get("organisation")),
            "plan": account_text(getattr(snapshot, "plan", None))}
