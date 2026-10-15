"""Account display fields from existing provider reports; no new network surface."""
from __future__ import annotations

from dataclasses import replace

__layer__ = "stores"


from .provider_account_view import account_text


def usage_snapshot(provider: str, snapshot):
    """Enrich the existing report before policy-only serialization, without refresh."""
    if provider != "openai-codex" or not getattr(snapshot, "identity", None):
        return snapshot
    from ._upstream_doors import codex_account_claims
    from hermes_cli.auth import resolve_codex_runtime_credentials
    try:
        runtime = resolve_codex_runtime_credentials(read_only=True)
        claims = codex_account_claims(runtime.get("api_key"), snapshot.identity)
    except Exception:  # No credential, error message or account ID crosses the projection.
        return snapshot
    profile = claims.get("https://api.openai.com/profile")
    profile = profile if isinstance(profile, dict) else {}
    email = account_text(profile.get("email")) or account_text(claims.get("email"))
    if email is None:
        return snapshot
    raw = dict(snapshot.raw or {})
    raw["account"] = {**(raw.get("account") or {}), "email": email}
    return replace(snapshot, raw=raw)


def nous_usage_snapshot():
    from agent.account_usage import build_nous_credits_snapshot
    from hermes_cli.nous_account import get_nous_portal_account_info

    account = get_nous_portal_account_info(force_fresh=True)
    # The builder owns the logged-out answer (None); a second gate here would
    # diverge from it.
    snapshot = build_nous_credits_snapshot(account)
    if snapshot is None:
        return None
    reported = {"email": account_text(getattr(account, "email", None)),
                "organisation": account_text(getattr(account, "org_name", None))}
    return replace(snapshot, raw={"account": reported})
