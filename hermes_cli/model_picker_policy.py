"""Non-secret model-picker provenance for the harness provider descriptors.

Compatibility is browse curation, NOT account entitlement. Codex uses a
bounded, account-scoped live catalog; credentials never enter this projection.
"""

from __future__ import annotations

MODEL_PICKER_POLICY_SCHEMA = "hermes.model_picker_policy/v1"

# Billing is route metadata, not login shape: e.g. Anthropic's external flow is
# also an API-key entrance. Unknown account terms must never become "included".
_ACCOUNT_ROUTES = frozenset({
    "openai-codex", "copilot", "copilot-acp", "claude-code", "qwen-oauth",
    "minimax-oauth", "xai-oauth",
})


def model_picker_policy_for(slug: str) -> dict:
    """Project a route, isolating discovery failures to that descriptor only."""
    policy = {
        "schema": MODEL_PICKER_POLICY_SCHEMA,
        "billing_mode": "account" if slug in _ACCOUNT_ROUTES else "catalog",
        "catalog_mode": "reference",
        "source": "models.dev",
    }
    if slug != "openai-codex":
        return policy

    policy["source"] = "hermes_cli.codex_models"
    try:
        from hermes_cli.auth_codex import _read_codex_tokens, _pool_codex_access_token
        from hermes_cli.auth import _read_global_codex_tokens_if_usable
        from hermes_cli.codex_models import get_verified_codex_model_ids

        # Match runtime's singleton > global > pool precedence using reads
        # only. The runtime resolver can import/refresh/probe and write auth,
        # which is inappropriate on the frequent provider-status path.
        try:
            token = _read_codex_tokens()["tokens"]["access_token"]
        except Exception:
            global_tokens = _read_global_codex_tokens_if_usable()
            token = (global_tokens or {}).get("access_token") or _pool_codex_access_token()
        model_ids = get_verified_codex_model_ids(token) if token else None
        if model_ids is not None and (not isinstance(model_ids, list) or any(
            not isinstance(mid, str) or not mid.strip() for mid in model_ids
        )):
            raise ValueError("Malformed live catalog")
        if model_ids is not None:
            policy["catalog_mode"] = "verified"
            policy["model_ids"] = list(dict.fromkeys(mid.strip() for mid in model_ids))
        else:
            policy["catalog_mode"] = "unavailable"
    except Exception:
        policy["catalog_mode"] = "unavailable"
    return policy
