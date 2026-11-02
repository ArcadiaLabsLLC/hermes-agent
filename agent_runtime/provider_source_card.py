"""The dashboard's "Anthropic Account" card names the EFFECTIVE source, and what it benches.

Upstream's ``hermes_cli/web_server_oauth.py::_anthropic_oauth_status`` lists the Hermes PKCE
grant first, so with a key AND a grant stored the card said "Hermes PKCE" while every turn
spent the key (``resolve_anthropic_token`` ranks env ``ANTHROPIC_API_KEY`` ahead of the pool).
The seam asks :func:`anthropic_card_status` first: it answers the source
``agent_runtime/provider_credential_source.py`` reports as effective — the same reader the
resolver, the pool and ``runtime.provider.list`` use — and appends to ``source_label`` each
stored source the effective one benches. ``None`` (no table, nothing stored, a raise) runs
upstream's body unchanged. Row ``RT-DASHBOARD-ANTHROPIC-CARD-EFFECTIVE-SOURCE``.

Never a secret: ``token_preview`` is upstream's own ``_truncate_token`` tail.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

__layer__ = "stores"

__all__ = ["anthropic_card_status"]

_ACCOUNT_ENV = ("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")


def _env_status(var: str, value: str, truncate: Callable[[Any], str]) -> dict:
    from hermes_cli.env_loader import format_secret_source_suffix

    return {"logged_in": True, "source": "env_var", "source_label": f"{var}{format_secret_source_suffix(var)}",
            "token_preview": truncate(value), "expires_at": None, "has_refresh_token": False}


def _effective_status(effective: str, truncate: Callable[[Any], str],
                      token_status: Callable[[str, str, dict], dict]) -> Optional[dict]:
    from agent import anthropic_credentials as creds

    from .provider_credential_source import API_KEY

    if effective == API_KEY:
        value = creds._first_env("ANTHROPIC_API_KEY")
        return _env_status("ANTHROPIC_API_KEY", value, truncate) if value else None
    var = next((name for name in _ACCOUNT_ENV if creds._first_env(name)), None)
    if var is not None:  # an env account token outranks the stored grant in the resolver
        return _env_status(var, creds._first_env(var), truncate)
    grant = creds.read_hermes_oauth_credentials()
    if grant and grant.get("accessToken"):
        return token_status("hermes_pkce", f"Hermes PKCE ({creds._get_hermes_oauth_file()})", grant)
    return None  # a borrowed Claude Code login: it has its own card


def anthropic_card_status(truncate: Callable[[Any], str],
                          token_status: Callable[[str, str, dict], dict]) -> Optional[dict]:
    """The card's status for the effective source, or None to run upstream's body."""
    try:
        from .provider_credential_source import credential_source_block

        block = credential_source_block("anthropic")
        if not block or not block.get("effective"):
            return None
        status = _effective_status(block["effective"], truncate, token_status)
    except Exception:
        return None
    if status is None:
        return None
    benched = [source for source in block["sources"] if source["present"] and source["id"] != block["effective"]]
    if benched:
        notes = ", ".join(f"{source['label']} stored, not spent" for source in benched)
        status["source_label"] = f"{status['source_label']} · {notes}"
    return {**status, "effective_source": block["effective"], "chosen_source": block.get("chosen"),
            "benched_sources": [source["id"] for source in benched]}
