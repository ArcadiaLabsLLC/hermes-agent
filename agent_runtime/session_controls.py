"""Native approval and speed policy for the Mission Chat conversation owner."""
from __future__ import annotations

from contextlib import contextmanager

from .session_control_store import SessionControlStore

__layer__ = "lanes"

APPROVAL_OPTIONS = (
    {"id": "manual", "label": "Ask", "description": "Ask before actions Hermes flags for approval."},
    {"id": "smart", "label": "Smart", "description": "Hermes reviews flagged actions and asks when uncertain."},
    {"id": "off", "label": "Off", "description": "Skip approval prompts. Tool restrictions and deny rules still apply."},
)
SPEED_OPTIONS = (
    {"id": "", "label": "Normal", "description": "Use standard processing."},
    {"id": "priority", "label": "Fast", "description": "Request faster processing. Additional usage or charges may apply."},
    {"id": "auto", "label": "Auto", "description": "Request fast processing during Hermes' window at each turn's start."},
    {"id": "cold", "label": "First turn", "description": "Request fast processing during a new conversation's first turn."},
)


def speed_options(provider, model, base_url=None, api_mode=None) -> list[dict]:
    from hermes_cli.models import normalize_provider, resolve_fast_mode_overrides

    if not provider or not model or not resolve_fast_mode_overrides(model, provider=provider, base_url=base_url):
        return []
    options = [dict(row) for row in SPEED_OPTIONS]
    from agent.fast_mode import CODEX_TIER_WORDS
    app_server = api_mode == "codex_app_server"
    unknown_codex_transport = normalize_provider(provider) == "openai-codex" and not api_mode
    ultrafast_transport = not unknown_codex_transport and (not app_server or "ultrafast" in CODEX_TIER_WORDS)
    if ultrafast_transport and resolve_fast_mode_overrides(model, provider=provider, base_url=base_url, tier="ultrafast"):
        options.insert(2, {"id": "ultrafast", "label": "Ultrafast",
                           "description": "Request this model's ultrafast tier. Higher usage or charges may apply."})
    return options


def resolved_session_controls(session_id: str, *, provider, model, base_url=None, api_mode=None) -> dict:
    from agent.fast_mode import parse_service_tier
    from hermes_cli.config import is_managed, load_config_readonly
    from .approval_surface_policy import approval_policy_mode, approval_policy_modes
    from tools.approval import approval_bypass_active

    config = load_config_readonly()
    saved = SessionControlStore().read(session_id)
    configured = approval_policy_mode()
    managed = is_managed()
    mode = configured if managed else saved.get("approval_mode", configured)
    known_options = {row["id"]: row for row in APPROVAL_OPTIONS}
    native_options = [known_options.get(value, {"id": value, "label": value.replace("_", " ").title(),
                      "description": "Use this native approval policy."}) for value in approval_policy_modes()]
    if mode not in {row["id"] for row in native_options}:
        raise ValueError("invalid stored approval policy")
    from .approval_surface_policy import scoped_approval_policy
    with scoped_approval_policy(mode):
        effective_mode = approval_policy_mode()
    approval_options = []
    for option in native_options:
        with scoped_approval_policy(option["id"]):
            if approval_policy_mode() == option["id"]:
                approval_options.append(option)
    bypass = approval_bypass_active(session_id)
    profile_tier = parse_service_tier((config.get("agent") or {}).get("service_tier")) or ""
    requested = profile_tier if managed else saved.get("service_tier", profile_tier)
    options = speed_options(provider, model, base_url, api_mode)
    available = {row["id"] for row in options}
    tier = requested if requested in available else ""
    reported_mode = "off" if bypass else effective_mode
    approval_source = "conversation" if "approval_mode" in saved else "profile"
    if len(approval_options) < 2:
        approval_source = "runtime_policy"
    if managed:
        approval_source = "managed"
    if bypass:
        approval_source = "bypass"
    return {
        "scope": "conversation", "provider": provider, "model": model, "api_mode": api_mode,
        "approval": {"mode": reported_mode, "requested": mode,
                     "label": next((row["label"] for row in native_options if row["id"] == reported_mode), "Not reported"),
                     "source": approval_source,
                     "options": approval_options,
                     "writable": len(approval_options) > 1 and not bypass and not is_managed()},
        "speed": {"state": "supported" if options else "unsupported", "requested": requested,
                  "effective": tier, "source": "managed" if managed else "conversation" if "service_tier" in saved else "profile",
                  "options": options, "writable": not is_managed(), "delivered": None},
    }


def apply_session_speed(agent, controls: dict) -> None:
    from agent.fast_mode import STATIC_TIERS
    from hermes_cli.models import resolve_fast_mode_overrides

    tier = controls["speed"]["effective"]
    overrides = dict(getattr(agent, "request_overrides", None) or {})
    overrides.pop("service_tier", None)
    overrides.pop("speed", None)
    if tier in STATIC_TIERS:
        overrides.update(resolve_fast_mode_overrides(
            controls["model"], provider=controls["provider"], base_url=getattr(agent, "base_url", None), tier=tier) or {})
    agent.service_tier = tier or None
    agent.request_overrides = overrides


def pending_session_approvals(session_id: str) -> list[dict]:
    from agent.redact import redact_sensitive_text
    from tools.approval import list_gateway_approvals

    return [{"id": row["request_id"],
             "command": redact_sensitive_text(str(row.get("command") or ""), force=True),
             "description": redact_sensitive_text(str(row.get("description") or "Approval required"), force=True),
             "choices": [{"id": "once", "label": "Allow once"}, {"id": "deny", "label": "Deny"}]}
            for row in list_gateway_approvals(session_id)]


@contextmanager
def session_approval_scope(session_id: str | None):
    """Use Hermes' authoritative queue/wait/timeout lifecycle on this operator root."""
    if not session_id:
        yield
        return
    from tools.approval import register_gateway_notify, unregister_gateway_notify
    from hermes_cli.config import is_managed
    from tools.approval_context import reset_current_session_key, set_current_session_key

    from .approval_surface_policy import approval_policy_mode, scoped_approval_policy

    mode = approval_policy_mode() if is_managed() else SessionControlStore().read(session_id).get("approval_mode", approval_policy_mode())
    token = set_current_session_key(session_id)
    # The existing queue is the replay authority, read by the attached console.
    register_gateway_notify(session_id, lambda _: None)
    try:
        with scoped_approval_policy(mode, gateway_session=True):
            yield
    finally:
        unregister_gateway_notify(session_id)
        reset_current_session_key(token)
