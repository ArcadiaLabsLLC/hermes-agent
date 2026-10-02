"""``runtime.default_model.set`` — the serve profile's ``model.default`` / ``model.provider``, written by upstream.

The runtime default the harness resolves (``load_agent_runtime_config``) follows
the top-level ``model:`` block of the SERVE profile's ``config.yaml``, unless an
``agent_runtime.default_*`` pin shadows it. Until this existed, no serve op could
move it: the launcher could set a persona default and an instance override, and
the bottom tier of the cascade was reachable only from a terminal — which edits
whichever profile the CLI's sticky ``active_profile`` names, not necessarily the
one serve runs (the envelope now reports both; ``snapshot/envelope.py``).

Every decision here is upstream's, called and not re-derived:

* the pick is validated by ``hermes_cli.model_switch.switch_model`` with
  ``is_global=True`` — the same pipeline as ``/model <m> --provider <p> --global``
  and the dashboard's main-slot assignment (catalog, alias, credential checks);
* its config shape is ``apply_model_selection`` (base_url / api_mode re-synced
  for the target route, so the old provider's endpoint never lingers);
* the write is ``hermes_cli.config.save_config``, under its own lock, refusing a
  config that failed to read rather than overwriting it.

Refusals are :class:`DefaultModelRefused` with a closed ``reason``:
``provider_required`` / ``model_required`` (params), ``config_managed`` (the
install's config is managed), ``config_unreadable`` (``config.yaml`` failed to
read; nothing is written), ``shadowed_by_runtime_override`` (an
``agent_runtime.default_model``/``default_provider`` pin would keep the write
from taking effect — refused rather than reported as applied),
``model_rejected`` (``switch_model`` said no; ``message`` is upstream's operator
text) and ``config_write_failed`` (the save raised; class name only).

A write that moves the pair appends ``runtime.default_model.set``. An
identical pick answers ``changed: false`` and appends nothing.
"""

from __future__ import annotations

from typing import Any

from hermes_time import now

from agent_runtime.events import EventLog
from agent_runtime.models import Event

__layer__ = "stores"

__all__ = [
    "DEFAULT_MODEL_REFUSAL_REASONS",
    "DefaultModelRefused",
    "set_runtime_default_model",
]

#: Every ``reason`` :class:`DefaultModelRefused` can carry — the closed set the
#: launcher binds against.
DEFAULT_MODEL_REFUSAL_REASONS: frozenset[str] = frozenset(
    {
        "provider_required",
        "model_required",
        "config_managed",
        "config_unreadable",
        "shadowed_by_runtime_override",
        "model_rejected",
        "config_write_failed",
    }
)

#: The longest model / provider id accepted (the instance override's own limit).
_MAX_ID_CHARS = 200


class DefaultModelRefused(Exception):
    """A refusal with a closed ``reason``; ``message`` is operator text, never a credential."""

    def __init__(self, reason: str, message: str = "", **data: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.data = data


def _clean_id(value: Any, reason: str) -> str:
    text = str(value or "").strip() if isinstance(value, str) else ""
    if not text or len(text) > _MAX_ID_CHARS:
        raise DefaultModelRefused(reason)
    return text


def _current_pair(cfg: dict) -> tuple[str | None, str | None]:
    from agent_runtime.config.loader import _top_level_model_authority

    model, provider = _top_level_model_authority(cfg)
    return provider, model


def _shadowing_pins(cfg: dict) -> list[str]:
    raw = cfg.get("agent_runtime")
    if not isinstance(raw, dict):
        return []
    return [
        f"agent_runtime.{key}"
        for key in ("default_model", "default_provider")
        if isinstance(raw.get(key), str) and raw.get(key).strip()
    ]


def _serve_profile() -> str:
    try:
        from agent_runtime.profile_context import active_profile_name

        return active_profile_name()
    except Exception:  # noqa: BLE001 — a label, never a reason to refuse the write
        return "default"


def set_runtime_default_model(
    *,
    provider: Any,
    model: Any,
    requested_by: str | None = None,
    event_log: EventLog | None = None,
) -> dict:
    """Validate, write and announce the serve profile's runtime default pair."""

    provider_id = _clean_id(provider, "provider_required")
    model_id = _clean_id(model, "model_required")

    from hermes_cli.config import (
        get_compatible_custom_providers,
        is_managed,
        load_config,
        save_config,
    )
    from hermes_cli.config_read_errors import FailedConfigRead
    from hermes_cli.model_switch import apply_model_selection, switch_model

    if is_managed():
        raise DefaultModelRefused("config_managed", "this install's configuration is managed")
    try:
        cfg = load_config()
    except Exception as exc:  # noqa: BLE001 — class name only
        raise DefaultModelRefused("config_unreadable", error_class=type(exc).__name__) from None
    if isinstance(cfg, FailedConfigRead) or not isinstance(cfg, dict):
        raise DefaultModelRefused("config_unreadable", "config.yaml failed to read; nothing was written")
    pins = _shadowing_pins(cfg)
    if pins:
        raise DefaultModelRefused(
            "shadowed_by_runtime_override",
            "an agent_runtime default pin overrides model.default; remove it first",
            pins=pins,
        )

    model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    result = switch_model(
        raw_input=model_id,
        explicit_provider=provider_id,
        is_global=True,
        current_provider=str(model_cfg.get("provider") or ""),
        current_model=str(model_cfg.get("default") or ""),
        current_base_url=str(model_cfg.get("base_url") or ""),
        user_providers=cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {},
        custom_providers=get_compatible_custom_providers(cfg),
    )
    if not result.success:
        raise DefaultModelRefused("model_rejected", str(result.error_message or "model switch rejected")[:500])

    before_provider, before_model = _current_pair(cfg)
    after_provider, after_model = result.target_provider, result.new_model
    profile = _serve_profile()
    changed = (before_provider, before_model) != (after_provider, after_model)
    if changed:
        cfg["model"] = apply_model_selection(cfg.get("model"), result)
        try:
            save_config(cfg)
        except Exception as exc:  # noqa: BLE001 — class name only
            raise DefaultModelRefused("config_write_failed", error_class=type(exc).__name__) from None
        try:
            # The serve process's boot record may still say "nothing configured";
            # every upstream main-model write path re-inventories it here.
            from hermes_cli.free_tier_bootstrap import reconcile_record

            reconcile_record()
        except Exception:  # noqa: BLE001 — the write landed; the gate re-checks on its own
            pass
        payload: dict[str, Any] = {
            "provider": after_provider,
            "model": after_model,
            "previous_provider": before_provider,
            "previous_model": before_model,
            "profile": profile,
        }
        if requested_by:
            payload["requested_by"] = str(requested_by)[:80]
        (event_log or EventLog()).append(
            Event(ts=now(), type="runtime.default_model.set", task_id=None, run_id=None, persona_id=None, payload=payload)
        )
    return {
        "ok": True,
        "changed": changed,
        "profile": profile,
        "provider": after_provider,
        "model": after_model,
        "api_mode": result.api_mode or None,
        "previous": {"provider": before_provider, "model": before_model},
        "warning": str(result.warning_message or "") or None,
    }
