"""Owned, revision-guarded edits through Hermes' native config writer."""
import hashlib
import hmac
import json
import os
import time

from .model import VERSION, Refusal, SubagentError, validate_request
from .references import references
from .settings_fields import FIELDS, ENVIRONMENT, ROUTE_KEYS, ADVANCED_ROUTE_KEYS, field_value, validate_changes

__layer__ = "lanes"


def _state(owner):
    from hermes_cli.config import get_config_path, require_readable_config_before_write, load_config_readonly, is_managed
    from hermes_cli.managed_scope import managed_config_keys
    from hermes_cli.config_read_errors import FailedConfigRead

    try:
        raw = require_readable_config_before_write()
        config = load_config_readonly()
        if isinstance(config, FailedConfigRead):
            raise ValueError("unreadable config")
        managed = managed_config_keys()
        locked = is_managed() or os.environ.get("HERMES_IGNORE_USER_CONFIG") == "1"
        fingerprint = hashlib.sha256(json.dumps([raw, config, sorted(managed), locked],
            sort_keys=True, default=str, ensure_ascii=True).encode()).hexdigest()
        revision = references.historical(owner, "settings", str(get_config_path()), {"hash": fingerprint})
        return raw, config, managed, locked, revision
    except (OSError, ValueError, RuntimeError) as exc:
        raise SubagentError(Refusal.CONFIG_UNREADABLE) from exc


def _snapshot(owner, profile_label):
    from hermes_cli.config import DEFAULT_CONFIG
    from tools.delegate_tool_config import delegation_defaults

    raw, config, managed, locked, revision = _state(owner)
    configured = raw.get("delegation") or {}
    delegation = config.get("delegation") or {}
    if not isinstance(configured, dict) or not isinstance(delegation, dict):
        raise SubagentError(Refusal.CONFIG_UNREADABLE)
    effective = delegation_defaults()
    advanced = any(delegation.get(key) for key in ADVANCED_ROUTE_KEYS)
    fields = []
    for key, field in FIELDS.items():
        pinned = "delegation." + key in managed
        source = "managed" if pinned or locked else "profile" if key in configured else "native_default"
        if source == "native_default" and key not in delegation and os.environ.get(ENVIRONMENT.get(key, "")):
            source = "environment"
        fields.append({"key": key, "value": field_value(key, effective.get(key)),
            "configured": field_value(key, configured[key]) if key in configured else None,
            "default": field_value(key, DEFAULT_CONFIG["delegation"].get(key, False if field.kind is bool else "")),
            "writable": not locked and not pinned and not (advanced and key in ROUTE_KEYS),
            "source": source, "applies": field.applies})
    return {"scope": "profile_defaults", "profile_label": profile_label, "revision": revision,
            "advanced_route": advanced, "fields": fields}


def _validate_route(config, changes):
    if not changes.keys() & set(ROUTE_KEYS):
        return
    from hermes_cli.model_switch import switch_model
    from hermes_cli.config import get_compatible_custom_providers

    route = {**(config.get("delegation") or {}), **changes}
    if any(route.get(key) for key in ADVANCED_ROUTE_KEYS):
        raise SubagentError(Refusal.MANAGED)
    if not route.get("model") and not route.get("provider"):
        return
    parent = config.get("model") or {}
    if not isinstance(parent, dict):
        parent = {"default": parent}
    model = route.get("model") or parent.get("default")
    if not model:
        raise SubagentError(Refusal.INVALID)
    result = switch_model(raw_input=model, explicit_provider=route.get("provider") or None,
        is_global=True, current_provider=parent.get("provider") or "", current_model=parent.get("default") or "",
        current_base_url=parent.get("base_url") or "", user_providers=config.get("providers") or {},
        custom_providers=get_compatible_custom_providers(config))
    if not result.success:
        raise SubagentError(Refusal.INVALID)
    if changes.get("model"):
        changes["model"] = result.new_model
    if changes.get("provider"):
        changes["provider"] = result.target_provider


def _save(owner, params, revalidate):
    from hermes_cli.config import CONFIG_WRITE_LOCK, save_config

    changes = dict(params["changes"])
    validate_changes(changes)
    _, config, _, _, _ = _state(owner)
    _validate_route(config, changes)
    with CONFIG_WRITE_LOCK:
        raw, _, managed, locked, revision = _state(owner)
        if locked or any("delegation." + key in managed for key in changes):
            raise SubagentError(Refusal.MANAGED)
        if not hmac.compare_digest(revision, params["expected_revision"]):
            raise SubagentError(Refusal.STALE)
        revalidate()
        updated = {**raw, "delegation": dict(raw.get("delegation") or {})}
        for key, value in changes.items():
            if value is None:
                updated["delegation"].pop(key, None)
            else:
                updated["delegation"][key] = value
        if updated != raw:
            try:
                save_config(updated, strip_defaults=False)
                saved, _, _, _, _ = _state(owner)
                confirmed = saved.get("delegation") or {}
                if any((key in confirmed if value is None else confirmed.get(key) != value)
                       for key, value in changes.items()):
                    raise SubagentError(Refusal.UNKNOWN)
            except (OSError, ValueError, RuntimeError) as exc:
                raise SubagentError(Refusal.UNKNOWN) from exc


def inspect_settings(operation, params, *, owner, profile_label, revalidate):
    from hermes_cli.config import CONFIG_WRITE_LOCK

    validate_request(operation, params)
    owner = ("profile_settings", owner)
    generation = references.require_generation(owner, params.get("expected_generation"))
    revalidate()
    if operation == "settings.set":
        _save(owner, params, revalidate)
    with CONFIG_WRITE_LOCK:
        data = _snapshot(owner, profile_label)
    try:
        revalidate()
    except Exception as exc:
        if operation == "settings.set":
            raise SubagentError(Refusal.UNKNOWN) from exc
        raise
    return {"version": VERSION, "generation": generation, "observed_at": time.time(), **data}
