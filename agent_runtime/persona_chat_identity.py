"""Pure field projections for resident persona-chat identity."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from typing import Any

from .cli_format import emit_json

__layer__ = "policy"


def revision_hash(value: Any) -> str:
    return hashlib.sha256(emit_json(value).encode("utf-8")).hexdigest()


def _as_plain(value: Any) -> Any:
    return (
        asdict(value) if is_dataclass(value) and not isinstance(value, type) else value
    )


# Construction inputs only: timestamps and activity do not change an actor.
PERSONA_IDENTITY_FIELDS: tuple[str, ...] = (
    "api_mode",
    "autonomy",
    "display_name",
    "hermes_profile",
    "id",
    "include_core_context_files",
    "include_profile_memory",
    "iteration_budget",
    "max_api_calls",
    "max_total_tokens",
    "max_wall_seconds",
    "model",
    "model_override_issued_at",
    "provider",
    "repo_scope",
    "repo_scope_label",
    "required_mcp_servers",
    "role",
    "schema_version",
    "skills",
    "soul_overlay_path",
    "system_prompt_path",
    "toolsets",
)

INSTANCE_IDENTITY_FIELDS: tuple[str, ...] = (
    "api_mode",
    "display_name",
    "id",
    "mode",
    "model",
    "model_override_issued_at",
    "persona_id",
    "profile_id",
    "provider",
    "realm_id",
    "reasoning_effort",
    "role",
    "runtime_root",
    "schema_version",
    "skill_overrides",
    "workspace_id",
)


def identity_revision(value: Any, fields: tuple[str, ...]) -> str:
    """Hash selected fields; absent and explicit None remain distinct."""

    plain = _as_plain(value)
    source = plain if isinstance(plain, dict) else None
    projected: dict[str, Any] = {}
    absent: list[str] = []
    missing = object()
    for name in fields:
        if source is not None:
            if name in source:
                projected[name] = source[name]
            else:
                absent.append(name)
            continue
        found = getattr(value, name, missing)
        if found is missing:
            absent.append(name)
        else:
            projected[name] = found
    return revision_hash({"fields": projected, "absent": absent})


_ACTOR_PERMISSION_FIELDS: tuple[str, ...] = ("mode", "source", "expired")


def actor_permission_identity(state: Any) -> dict[str, Any]:
    """Counters are transient; expired grants change the actor's permissions."""

    source = state if isinstance(state, dict) else {}
    return {name: source.get(name) for name in _ACTOR_PERMISSION_FIELDS}


# Model, tools, permissions and runtime root already have resolved components.
# Budgets and terminal grants are refreshed per turn, not frozen in the actor.
ACTOR_CONFIG_IDENTITY_FIELDS: tuple[str, ...] = ()

# The chat override is resolved into provider/model before signature construction.
# Usage anchors, pruning counters and native thread bindings are durable execution
# state, not construction inputs. Never hash the whole session record.
SESSION_MODEL_CONFIG_IDENTITY_FIELDS: tuple[str, ...] = ()

# Inputs the provider resolver supplies to construction, including local reloads.
_RESOLVED_RUNTIME_FIELDS = (
    "provider",
    "model",
    "api_mode",
    "base_url",
    "api_key",
    "local_parameters",
)


def resolved_runtime_revision(runtime: dict[str, Any]) -> str:
    """Private digest only; credentials and endpoints never enter receipts."""
    return identity_revision(runtime, _RESOLVED_RUNTIME_FIELDS)
