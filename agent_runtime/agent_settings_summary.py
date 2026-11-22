"""An agent's safe settings: the short, fixed list of fields a device driving this engine may read.

Row ``RT-FU-ANOTHER-DEVICE-SEES-A-SHORT-LIST-OF-SAFE-AGENT-SETTINGS-NEVER-THE-CONFIG-FILE``. The
agent's ``config.yaml`` is never served (owner 2026-11-22): it can hold inline secrets (a custom
endpoint's ``model.api_key``, MCP servers' ``env`` and ``headers``). In its place the per-agent
detail verb ``runtime.persona.instance.detail`` carries a ``settings`` block built HERE, at the
verb's read tier, so a Look device sees it too (owner 2026-11-22, "go as reccomended").

The block is an ALLOWLIST: :data:`SAFE_SETTINGS_FIELDS` is the one tuple of names, and each value
is built from its own typed reader, key by key. Nothing here holds, filters or redacts a config
dict, so a key outside the tuple (a base URL, a key, an MCP command, env or header) has no path
into the reply. The source is the agent's own resolution, never the runtime's
``migrations.effective_config_summary`` (that is the RUNTIME's config, redaction-based):

* ``model`` / ``provider`` — what a chat turn with no per-chat override runs on:
  :func:`agent_runtime.persona_runtime.turn_provider_model` over the seat's overrides
  (:func:`agent_runtime.models.apply_instance_model_overrides`) and the runtime default;
* ``toolsets`` — the bound profile's ``toolsets:`` declaration as
  :func:`agent_runtime.persona_profiles.declared_lane_toolsets` resolves it (the lane default when
  the profile declares none).

Eternia shows these fields and never keeps its own copy of the list.
"""

from __future__ import annotations

from typing import Any

__layer__ = "lanes"

__all__ = ["SAFE_SETTINGS_FIELDS", "agent_settings_summary"]

#: The ONE list of an agent's settings a device may read, in the order they are shown.
SAFE_SETTINGS_FIELDS: tuple[str, ...] = ("model", "provider", "toolsets")


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def agent_settings_summary(persona, instance=None) -> dict[str, Any]:
    """The ``settings`` block for ``persona`` (seen through ``instance``'s overrides when given).

    Every key of :data:`SAFE_SETTINGS_FIELDS` is present; an unresolved value is ``None`` (model,
    provider) or ``[]`` (toolsets), never a guess."""

    from .config import load_agent_runtime_config
    from .models import apply_instance_model_overrides
    from .persona_profiles import declared_lane_toolsets
    from .persona_runtime import turn_provider_model

    seen = apply_instance_model_overrides(persona, instance)
    cfg = load_agent_runtime_config()
    provider, model = turn_provider_model(seen, None, None, cfg.default_provider, cfg.default_model)
    declaration = declared_lane_toolsets(persona)
    values = {
        "model": _text(model),
        "provider": _text(provider),
        "toolsets": [name for name in (_text(item) for item in declaration.declared) if name],
    }
    return {name: values[name] for name in SAFE_SETTINGS_FIELDS}
