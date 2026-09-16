"""Non-secret model-picker provenance for the harness provider descriptors.

Compatibility is browse curation, NOT account entitlement. This projection never
requests a token or live catalog and never writes config or cache files.
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
        from hermes_cli.codex_models import get_codex_model_ids

        # NO access_token: the canonical owner re-resolves CODEX_HOME at call
        # time and preserves its offline account-gated-model safeguards.
        model_ids = get_codex_model_ids()
        if not isinstance(model_ids, list) or any(
            not isinstance(mid, str) or not mid.strip() for mid in model_ids
        ):
            raise ValueError("Malformed compatibility catalog")
        policy["catalog_mode"] = "compatibility"
        policy["model_ids"] = list(dict.fromkeys(mid.strip() for mid in model_ids))
    except Exception as exc:
        policy["catalog_mode"] = "unavailable"
        # Exception text may contain credentials or paths; only the class is
        # safe to cross this public status boundary.
        policy["error"] = type(exc).__name__
    return policy
