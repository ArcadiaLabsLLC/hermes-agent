"""Non-secret model-picker provenance for the harness provider descriptors.

Compatibility is browse curation, NOT account entitlement. Codex uses a
bounded, account-scoped live catalog; credentials never enter this projection.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional

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
        from hermes_cli.auth_codex import _pool_codex_credential, _read_codex_tokens

        # Match runtime's singleton > pool precedence using reads only. The runtime resolver
        # can import/refresh/probe and write auth, which is inappropriate on the frequent
        # provider-status path. The global-root rung that used to sit between these two was
        # retired by the 2026-09-17 theme-7 ruling: a persona that shares the head's
        # credentials has that store bound as its ACTIVE one, so the singleton read IS it.
        try:
            token = _read_codex_tokens()["tokens"]["access_token"]
        except Exception:
            token = _pool_codex_credential()[0]
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


# Process-local only. The key is a one-way token digest; neither credentials nor
# account identifiers cross the provider-visibility wire.
_picker_lock = threading.Lock()


def _picker_cache_path() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "cache" / "codex-model-picker.json"


def get_verified_codex_model_ids(access_token: str) -> Optional[List[str]]:
    """Visible live base IDs plus Hermes-local 900K context aliases.

    None means unverified; an empty list is a valid live empty account catalog.
    The bounded disk cache spans short-lived `harness providers` processes.
    No unverified base models (including Astra or Spark) are synthesized.
    """
    from agent.codex_headers import codex_account_headers

    if not access_token or not codex_account_headers(access_token).get("ChatGPT-Account-ID"):
        return None
    key = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
    now = time.time()
    with _picker_lock:
        path = _picker_cache_path()
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (cached.get("key") == key and cached.get("expires", 0) > now
                    and isinstance(cached.get("models"), list)
                    and all(isinstance(mid, str) for mid in cached["models"])):
                return list(cached["models"]) if cached.get("verified") else None
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        models = _fetch_verified_models_from_api(access_token)
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as handle:
                json.dump({"key": key, "expires": time.time() + (300 if models is not None else 30),
                           "verified": models is not None, "models": models or []}, handle)
                temporary = Path(handle.name)
            os.replace(temporary, path)
        except OSError:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return models


def _fetch_verified_models_from_api(access_token: str) -> Optional[List[str]]:
    """The account's live catalog through upstream's reader, or None when unverified.

    Upstream owns the request: ``codex_account_headers`` (account + residency
    headers) and ``fetch_codex_catalog_entries`` (newest-client URL first, the
    ``0.0.0`` sentinel as fallback). This function only ranks the answer.
    """
    try:
        import httpx
        from agent.codex_headers import codex_account_headers
        from agent.model_metadata import fetch_codex_catalog_entries
        from hermes_cli.codex_models import _add_context_variants, _ranked_slugs

        headers = {"Authorization": f"Bearer {access_token}", **codex_account_headers(access_token)}
        entries, status = fetch_codex_catalog_entries(lambda url: httpx.get(url, headers=headers, timeout=5))
        if status != 200:
            return None
        return _add_context_variants(_ranked_slugs(entries))
    except Exception:
        # HTTP exception messages may contain request headers. Never log them.
        return None
