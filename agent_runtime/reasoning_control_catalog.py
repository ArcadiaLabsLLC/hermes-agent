"""The scoped reasoning-control catalog: serving-catalog effort facts, cached per profile scope.

Moved out of the upstream ``hermes_cli/models_reasoning_caps.py`` (footprint audit
2026-10-15, lane R). It shares that module's disk cache file and TTL through
``agent_runtime/_upstream_doors.py`` (``reasoning_caps_disk_*``); upstream keeps one
two-line hook in ``_seed_reasoning_caps`` that records the OpenRouter/Nous catalogs here.
Writers: ``hermes_cli/models.py::fetch_github_model_catalog`` (copilot) and
``hermes_cli/codex_models.py::_fetch_models_from_api`` (openai-codex). Readers: the
copilot and openai-codex provider profiles (``cached_control_efforts``) and
``agent_runtime/reasoning_capabilities.py`` (``cached_control_capabilities``).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from agent_runtime import _upstream_doors as doors

__layer__ = "stores"
logger = logging.getLogger(__name__)

Caps = dict[str, Optional[dict[str, Any]]]


def _control_catalog_key(provider: str) -> str:
    """Opaque scope key: profile, credential-owner revision, endpoint and env keys.

    Contains no credential bytes and never resolves or refreshes a credential.
    Model/effort preference changes do not invalidate a provider's catalog.
    """
    from agent.secret_scope import get_secret
    from hermes_cli.auth import authentication_owner_stamps
    from hermes_constants import get_hermes_home
    from providers import get_provider_profile
    from hermes_cli.config import load_config_readonly

    profile = get_provider_profile(provider)
    env_names = (*getattr(profile, "env_vars", ()), "NOUS_INFERENCE_BASE_URL", "HERMES_CODEX_BASE_URL")
    env = {name: hashlib.sha256((get_secret(name) or "").encode()).hexdigest() for name in env_names}
    cfg = load_config_readonly() or {}
    model = cfg.get("model") or {}
    endpoint = model.get("base_url") if isinstance(model, dict) else None
    scope = [str(get_hermes_home()), authentication_owner_stamps(), env, endpoint]
    digest = hashlib.sha256(json.dumps(scope, default=str, sort_keys=True).encode()).hexdigest()
    return f"reasoning-control:{provider}:{digest}"


def cached_control_capabilities(provider: str, model: str, *, base_url: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Strict cache read for snapshot/RPC inspection: no fetch, refresh or warmer."""
    caps, age = doors.reasoning_caps_disk_load(_control_catalog_key(provider))
    if caps is None or age >= doors.reasoning_caps_disk_ttl():
        return None
    result = caps.get(model)
    if result is None and provider == "openai-codex":
        from agent.model_metadata import strip_codex_context_variant_suffix
        result = caps.get(strip_codex_context_variant_suffix(model))
    if not isinstance(result, dict):
        return None
    endpoint = result.get("endpoint_scope")
    if base_url and endpoint and endpoint != _endpoint_scope(base_url):
        return None
    return dict(result)


def _endpoint_scope(base_url: str) -> str:
    return hashlib.sha256(base_url.strip().rstrip("/").encode()).hexdigest()


def save_control_capabilities(provider: str, caps: Caps) -> None:
    """Record ``caps`` under ``provider``'s scope key; never fails the discovery that found them."""
    try:
        doors.reasoning_caps_disk_save(_control_catalog_key(provider), caps)
    except Exception as exc:
        # Optional inspection metadata must not fail successful model discovery.
        logger.debug("Failed to scope reasoning-control catalog: %s", exc, exc_info=True)


def cached_control_efforts(provider: str, model: Optional[str], *, base_url: Optional[str] = None) -> Optional[tuple[str, ...]]:
    """Provider hook vocabulary: None is unknown; empty is definitive unsupported."""
    caps = cached_control_capabilities(provider, model or "", base_url=base_url)
    if caps is None:
        return None
    if caps.get("supports_reasoning") is False:
        return ()
    levels = caps.get("supported_efforts")
    if not isinstance(levels, list):
        return None
    from agent.reasoning_effort import EFFORT_LADDER
    return tuple(level for level in EFFORT_LADDER
                 if level in levels and not (level == "none" and caps.get("mandatory")))


def record_control_catalog(provider: str, items: Any, *, base_url: Optional[str] = None) -> None:
    """Reuse an already-fetched serving catalog. No new request or model allowlist."""
    if not isinstance(items, list):
        return
    caps: Caps = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        model = item.get("slug") or item.get("id")
        if not isinstance(model, str) or not model.strip():
            continue
        if provider == "copilot":
            detail = item.get("capabilities")
            supports = detail.get("supports") if isinstance(detail, dict) else None
            levels = supports.get("reasoning_effort") if isinstance(supports, dict) else None
        else:
            levels = item.get("supported_reasoning_levels")
        if not isinstance(levels, list):
            caps[model.strip()] = None
            continue
        efforts: list[str] = []
        descriptions: dict[str, str] = {}
        for level in levels:
            effort = level.get("effort") if isinstance(level, dict) else level
            if isinstance(effort, str) and effort.strip():
                effort = effort.strip().lower()
                if effort not in efforts:
                    efforts.append(effort)
                description = level.get("description") if isinstance(level, dict) else None
                if isinstance(description, str) and description.strip():
                    descriptions[effort] = description.strip()
        default = item.get("default_reasoning_level") or item.get("default_reasoning_effort")
        caps[model.strip()] = {"supports_reasoning": bool(efforts), "supported_efforts": efforts,
                              "default_effort": default if isinstance(default, str) else None,
                              "descriptions": descriptions}
        if base_url:
            caps[model.strip()]["endpoint_scope"] = _endpoint_scope(base_url)
    if caps:
        save_control_capabilities(provider, caps)
