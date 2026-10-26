"""Head-scoped suggestion policy; config.yaml remains the only preference store."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from hermes_yaml import YAMLError

from agent_runtime.harness_settings import SETTINGS_PATH, harness_setting

__layer__ = "stores"
TASK = "console_next_prompt"
FIELDS = {"enabled": False, "max_context_messages": 4, "cooldown_seconds": 3}
ROUTE_FIELDS = frozenset({"provider", "model", "base_url"})


class SuggestionRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@contextmanager
def suggestion_home(home: Path):
    """Never inherit a persona's model or projected config into background work."""
    from agent_runtime.profile_context import process_home_scope
    from hermes_cli.config_read_scope import readonly_config_scope
    from agent.auxiliary_client import scoped_runtime_main

    with process_home_scope(home, head_home=home), readonly_config_scope(None), scoped_runtime_main({}):
        yield


def policy_revision(config: dict) -> str:
    policy = {key: harness_setting("console_suggestions_" + key, default, config=config)
              for key, default in FIELDS.items()}
    policy["generation"] = harness_setting("console_suggestions_generation", "", config=config)
    policy["auxiliary"] = config.get("auxiliary", {})
    policy["model"] = config.get("model", {})
    return hashlib.sha256(json.dumps(policy, sort_keys=True, default=str).encode()).hexdigest()


def policy_snapshot(config: dict, *, writable: bool = True) -> dict:
    values = {key: harness_setting("console_suggestions_" + key, default, config=config)
              for key, default in FIELDS.items()}
    valid = (type(values["enabled"]) is bool
             and type(values["max_context_messages"]) is int and 2 <= values["max_context_messages"] <= 10
             and type(values["cooldown_seconds"]) is int and 0 <= values["cooldown_seconds"])
    # Invalid optional tuning fails closed, but must remain decodable so the
    # operator can disable or repair it without overwriting unrelated fields.
    if type(values["max_context_messages"]) is not int or not 2 <= values["max_context_messages"] <= 10:
        values["max_context_messages"] = FIELDS["max_context_messages"]
    if type(values["cooldown_seconds"]) is not int or values["cooldown_seconds"] < 0:
        values["cooldown_seconds"] = FIELDS["cooldown_seconds"]
    route = (config.get("auxiliary") or {}).get(TASK) or {}
    override = {key: route[key] for key in ROUTE_FIELDS if isinstance(route.get(key), str) and route[key]}
    if override.get("provider") == "auto":
        override.pop("provider")
    # Endpoint credentials are never returned to a UI or notification stream.
    if "base_url" in override:
        parsed = urlsplit(override["base_url"])
        if parsed.username or parsed.password or parsed.query:
            override["base_url"] = ""
    return {"contract": 1, **values, "enabled": valid and values["enabled"],
            "settings_revision": policy_revision(config), "writable": writable,
            "reason": None if valid else "config_invalid", "routing_mode": "override" if override else "inherited",
            "auxiliary_override": override or None, "model_status": "inherited" if not override else "configured"}


class SuggestionSettings:
    def __init__(self, home: Path):
        self.home = home

    def read(self) -> dict:
        from hermes_cli import config, managed_scope
        with suggestion_home(self.home):
            try:
                raw = config.read_user_config_raw()
                writable = not config.is_managed() and not managed_scope.is_key_managed(
                    ".".join((*SETTINGS_PATH, "console_suggestions_enabled")))
                return policy_snapshot(raw, writable=writable)
            except (OSError, ValueError, TypeError, AttributeError, YAMLError):
                return {**policy_snapshot({}), "enabled": False, "writable": False, "reason": "config_unreadable"}

    def write(self, params: dict) -> dict:
        from hermes_cli.plugins_state import update_plugin_configuration
        changes = {key: value for key, value in params.items() if key in FIELDS or key == "auxiliary_override"}
        if not changes:
            raise SuggestionRefused("changes_required")
        self._validate(changes)
        paths = {(*SETTINGS_PATH, "console_suggestions_" + key) for key in changes if key in FIELDS}
        paths.add((*SETTINGS_PATH, "console_suggestions_generation"))
        if "auxiliary_override" in changes:
            paths.update(("auxiliary", TASK, key) for key in ROUTE_FIELDS)

        def update(raw):
            if params.get("expected_revision") != policy_revision(raw):
                raise SuggestionRefused("stale_revision")
            target = raw
            for key in SETTINGS_PATH:
                target = target.setdefault(key, {})
            for key, value in changes.items():
                if key in FIELDS:
                    target["console_suggestions_" + key] = value
            target["console_suggestions_generation"] = uuid4().hex
            if "auxiliary_override" in changes:
                route = raw.setdefault("auxiliary", {}).setdefault(TASK, {})
                for key in ROUTE_FIELDS:
                    route.pop(key, None)
                route.update(deepcopy(changes["auxiliary_override"] or {}))

        with suggestion_home(self.home):
            try:
                update_plugin_configuration(update, paths=paths)
            except PermissionError as exc:
                raise SuggestionRefused("config_managed") from exc
        return self.read()

    @staticmethod
    def _validate(changes: dict) -> None:
        validators = {
            "enabled": (lambda value: type(value) is bool, "invalid_enabled"),
            "max_context_messages": (lambda value: type(value) is int and 2 <= value <= 10, "invalid_context_window"),
            "cooldown_seconds": (lambda value: type(value) is int and value >= 0, "invalid_cooldown"),
        }
        for key, (validate, reason) in validators.items():
            if key in changes and not validate(changes[key]):
                raise SuggestionRefused(reason)
        _validate_suggestion_route(changes.get("auxiliary_override"))


def _validate_suggestion_route(value):
    if value is None:
        return
    if (not isinstance(value, dict) or not value or set(value) - ROUTE_FIELDS
            or any(not isinstance(item, str) or not item.strip() or len(item) > 2048 for item in value.values())):
        raise SuggestionRefused("invalid_auxiliary_override")
    if value.get("base_url") and not value["base_url"].startswith(("http://", "https://")):
        raise SuggestionRefused("invalid_auxiliary_override")
    endpoint = urlsplit(value.get("base_url", ""))
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise SuggestionRefused("invalid_auxiliary_override")
