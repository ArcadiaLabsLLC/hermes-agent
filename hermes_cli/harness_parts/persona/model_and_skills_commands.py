"""Model and skill verbs: instance/template ``set-model`` and ``set-skills``, with their request validation.

Separate because both are compare-and-set writes with their own typed error payloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from agent_runtime.cli_format import emit_json
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.coordinator_permissions import review_coordinator_budget
from agent_runtime.persona_assignments import (
    _safe_skill_overrides,
    PersonaInstanceStore,
    StaleModelOverrideWrite,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.root_observability import attach_root_observability
from agent_runtime.store import AgentStore
from hermes_cli.flag_binding import list_flag_or_absent
from .chat_coordinator import (
    _coordinator_actor_id,
    _coordinator_confirm_payload,
    _coordinator_scope_from_args,
)
from .chat_session import _safe_chat_model_override_value
from .chat_target import _persona_by_id

__layer__ = "lanes"
__all__ = [
    "_cmd_persona_instance_set_model",
    "_cmd_persona_set_model",
    "_cmd_persona_set_skills",
]


class _SetModelRequestError(ValueError):
    """Typed validation failure for the set-model verbs (machine-readable error_code)."""

    def __init__(self, error_code: str, message: str, *, extra: dict | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.extra = dict(extra or {})


def _set_model_error_payload(exc: _SetModelRequestError, **identity) -> dict:
    return {
        "ok": False,
        "error_code": exc.error_code,
        "error": safe_assignment_text(str(exc), limit=320),
        **exc.extra,
        **identity,
        "next_expected": "fix the arguments and retry; no model settings were changed",
    }


def _parse_issued_at_arg(raw_value) -> datetime | None:
    """``--issued-at`` → aware/naive datetime, or ``None`` when not supplied.

    One spelling for every supersede-clock verb (``persona set-model``,
    ``persona instance set-model``, ``persona set-skills``): the launcher stamps
    ``Z``-suffixed timestamps that ``datetime.fromisoformat`` rejects on the
    Python versions this repo still supports, and a second copy of that
    workaround is a second place for it to go stale.
    """

    raw_issued = str(raw_value or "").strip()
    if not raw_issued:
        return None
    text = raw_issued[:-1] + "+00:00" if raw_issued.endswith("Z") else raw_issued
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise _SetModelRequestError("invalid_value", f"--issued-at is not an ISO-8601 timestamp: {raw_issued}") from exc


def _validated_set_model_request(args) -> dict:
    """Shared validation for `persona set-model` / `persona-instance set-model`.

    Provider must resolve in the plugin registry (canonical name is persisted;
    api_mode is derived from the provider profile so a lane switch can never
    strand a stale api_mode). Model ids are shape-checked only — the harness
    has no catalog authority, so catalog membership is deliberately NOT faked
    (`model_catalog_checked: false` in the envelope).
    """
    use_default = bool(getattr(args, "use_default", False) or getattr(args, "use_profile_default", False))
    try:
        provider_raw = _safe_chat_model_override_value(getattr(args, "provider", None), field="provider")
        model = _safe_chat_model_override_value(getattr(args, "model", None), field="model")
    except ValueError as exc:
        raise _SetModelRequestError("invalid_value", str(exc)) from exc
    # Reasoning-effort override rides the same set-model lane (per-instance).
    # ``None`` = not provided; ``""`` = clear back to the runtime default; a
    # level ("none"/minimal/low/medium/high/xhigh) sets it. Shape-checked here
    # so a bad value is a typed rejection, not a downstream ValueError.
    reasoning_raw = getattr(args, "reasoning_effort", None)
    reasoning_effort: str | None = None
    if reasoning_raw is not None:
        from hermes_constants import VALID_REASONING_EFFORTS

        reasoning_effort = str(reasoning_raw).strip().lower()
        if reasoning_effort and reasoning_effort != "none" and reasoning_effort not in VALID_REASONING_EFFORTS:
            raise _SetModelRequestError(
                "invalid_value",
                f"invalid reasoning effort: {reasoning_raw!r} (expected one of none, "
                f"{', '.join(VALID_REASONING_EFFORTS)})",
            )
    reasoning_provided = reasoning_effort is not None
    if use_default and (provider_raw or model or reasoning_provided):
        raise _SetModelRequestError("conflicting_args", "--use-default cannot be combined with --provider, --model, or --reasoning-effort")
    if not use_default and not provider_raw and not model and not reasoning_provided:
        raise _SetModelRequestError("missing_args", "pass --provider and/or --model, --reasoning-effort, or the use-default flag to clear the override")
    provider = None
    api_mode = None
    warnings: list[dict] = []
    if provider_raw:
        from providers import get_provider_profile, list_providers

        profile = get_provider_profile(provider_raw)
        from agent_runtime.local_llama_adapter import is_local_llama_provider
        if is_local_llama_provider(provider_raw):
            # Either id stores the launcher's ``local-llama-hermes`` (the profile's name).
            from agent_runtime.local_llama_adapter.provider import provider_profile
            profile = provider_profile()
        if profile is None:
            known = sorted({str(item.name) for item in list_providers()})
            raise _SetModelRequestError(
                "unknown_provider",
                f"unknown provider: {provider_raw}",
                extra={"known_providers": known},
            )
        provider = str(profile.name)
        api_mode = str(getattr(profile, "api_mode", "") or "") or None
        import os as _os

        env_vars = tuple(getattr(profile, "env_vars", ()) or ())
        if env_vars and not any(_os.environ.get(name) for name in env_vars):
            warnings.append(
                {
                    "code": "provider_credentials_not_detected",
                    "message": f"no API-key env var ({', '.join(env_vars)}) detected on this host; OAuth/auth-store credentials may still apply at runtime",
                }
            )
    issued_at = _parse_issued_at_arg(getattr(args, "issued_at", None))
    return {
        "use_default": use_default,
        "provider": provider,
        "model": model,
        "api_mode": api_mode,
        "reasoning_effort": reasoning_effort,
        "issued_at": issued_at,
        "warnings": warnings,
    }


def _cmd_persona_instance_set_model(args) -> int:
    cfg = load_agent_runtime_config()
    persona_instance_id = safe_assignment_token(args.persona_instance_id)
    if not persona_instance_id:
        data = {"ok": False, "error_code": "persona_not_found", "error": "persona_instance_id is required"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    store = PersonaInstanceStore()
    try:
        target = store.get(persona_instance_id)
    except Exception:
        data = {"ok": False, "error_code": "persona_not_found", "error": f"persona instance not found: {persona_instance_id}"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    coordinator_id = _coordinator_actor_id(args)
    if coordinator_id:
        persona = _persona_by_id(cfg, target.persona_id)
        scope = _coordinator_scope_from_args(args, cfg, persona)
        auth = review_coordinator_budget("persona.instance.set_model", scope, target, actor=coordinator_id, coordinator_id=coordinator_id)
        if not auth.ok:
            data = _coordinator_confirm_payload("persona.instance.set_model", coordinator_id, auth)
            print(emit_json(data) if args.json else data["status"])
            return 2
    try:
        request = _validated_set_model_request(args)
    except _SetModelRequestError as exc:
        data = _set_model_error_payload(exc, persona_instance_id=persona_instance_id, scope="agent_instance")
        print(emit_json(data) if args.json else data["error"])
        return 2
    status = "applied"
    try:
        updated = store.update_profile(
            persona_instance_id,
            provider=request["provider"],
            model=request["model"],
            api_mode=request["api_mode"],
            reasoning_effort=request["reasoning_effort"],
            clear_model_override=request["use_default"],
            model_issued_at=request["issued_at"],
            requested_by=getattr(args, "requested_by", None) or "operator",
        )
    except StaleModelOverrideWrite as exc:
        updated = exc.instance
        status = "superseded"
    except ValueError as exc:
        data = {"ok": False, "error_code": "invalid_value", "error": safe_assignment_text(str(exc), limit=320), "persona_instance_id": persona_instance_id}
        print(emit_json(data) if args.json else data["error"])
        return 2
    try:
        persona = _persona_by_id(cfg, updated.persona_id)
    except Exception:
        persona = None
    default_provider = getattr(persona, "provider", None) or getattr(cfg, "default_provider", None)
    default_model = getattr(persona, "model", None) or getattr(cfg, "default_model", None)
    data = {
        "ok": True,
        "status": status,
        "applied": status == "applied",
        "scope": "agent_instance",
        "cleared": bool(request["use_default"]) and status == "applied",
        "persona_instance_id": updated.id,
        "persona_id": updated.persona_id,
        "backing_profile": updated.profile_id,
        "provider": updated.provider,
        "model": updated.model,
        "api_mode": updated.api_mode,
        "reasoning_effort": updated.reasoning_effort,
        "default_provider": default_provider,
        "default_model": default_model,
        "effective_provider": updated.provider or default_provider,
        "effective_model": updated.model or default_model,
        "model_is_instance_override": bool(updated.provider or updated.model or updated.reasoning_effort),
        "model_catalog_checked": False,
        "persistence": "persona_instance_store",
        "warnings": request["warnings"],
        "next_expected": (
            "a newer model write already applied for this agent; refresh the Harness snapshot for current truth"
            if status == "superseded"
            else "refresh Harness snapshot; this agent's future chat turns and mission runs use the instance override unless a chat-session override is active"
        ),
    }
    print(emit_json(data) if args.json else f"{status}: {updated.id} model={data['effective_model']} provider={data['effective_provider']}")
    return 0


def _template_write_store_target(store, persona_id: str, *, what: str):
    """Resolve the STORE row a template-tier (profile-default) write lands on.

    Shared by ``persona set-model`` and ``persona set-skills`` because both
    write the same tier and must answer the same three questions identically:

    * ``profile:<name>`` resolves to the SINGLE store row bound to that profile
      (several rows ⇒ ``ambiguous_profile_persona``, none ⇒ the refusal below);
    * a config-only catalog id is REFUSED ``persona_not_persisted`` rather than
      promoted into a store row. Minting a row to persist one field would
      freeze EVERY other field of that persona at its write-time value, because
      ``config.ensure_persisted_personas`` merges ``{**catalog, **stored}`` and
      a store row wins wholesale. The refusal names what would have happened;
      silent promotion could not.

    Returns ``(target, None)`` or ``(None, refusal_payload)`` — never both, and
    never raises for a resolution outcome.
    """

    if persona_id.startswith("profile:"):
        profile_name = persona_id.split(":", 1)[1]
        candidates = [item for item in store.list_all() if str(getattr(item, "hermes_profile", "") or "") == profile_name]
        if not candidates:
            return None, {
                "ok": False,
                "error_code": "persona_not_persisted",
                "error": f"{what} can only be set on store-persisted agents; {persona_id} has no backing agent record",
                "persona_id": persona_id,
            }
        if len(candidates) > 1:
            return None, {
                "ok": False,
                "error_code": "ambiguous_profile_persona",
                "error": f"{persona_id} is backed by multiple store personas; target one explicitly",
                "persona_id": persona_id,
                "candidates": sorted(str(item.id) for item in candidates),
            }
        return candidates[0], None
    try:
        return store.get(persona_id), None
    except Exception:
        return None, {
            "ok": False,
            "error_code": "persona_not_persisted",
            "error": f"{what} can only be set on store-persisted agents; {persona_id} is not in the agent store",
            "persona_id": persona_id,
        }


def _cmd_persona_set_model(args) -> int:
    cfg = load_agent_runtime_config()
    raw_id = str(getattr(args, "persona_id", "") or "").strip()
    try:
        persona = _persona_by_id(cfg, raw_id)
    except ValueError:
        persona = None
    if persona is None:
        data = {"ok": False, "error_code": "persona_not_found", "error": f"unknown persona: {safe_assignment_token(raw_id)}"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    try:
        request = _validated_set_model_request(args)
    except _SetModelRequestError as exc:
        data = _set_model_error_payload(exc, persona_id=str(getattr(persona, "id", "") or raw_id), scope="agent_default")
        print(emit_json(data) if args.json else data["error"])
        return 2
    if request["reasoning_effort"] is not None:
        # Reasoning effort is a per-agent-instance override for now (AgentPersona
        # carries no reasoning field). Reject at the profile-default scope rather
        # than silently dropping it.
        data = _set_model_error_payload(
            _SetModelRequestError(
                "unsupported_scope",
                "reasoning effort can only be set per agent instance (persona.instance.set_model), not on the profile default",
            ),
            persona_id=str(getattr(persona, "id", "") or raw_id),
            scope="agent_default",
        )
        print(emit_json(data) if args.json else data["error"])
        return 2
    store = AgentStore()
    persona_id = str(getattr(persona, "id", "") or "")
    target, refusal = _template_write_store_target(store, persona_id, what="agent defaults")
    if target is None:
        print(emit_json(refusal) if args.json else refusal["error"])
        return 2
    status = "applied"
    issued_at = request["issued_at"]
    if issued_at is not None and getattr(target, "model_override_issued_at", None) is not None:
        issued = issued_at if issued_at.tzinfo is not None else issued_at.replace(tzinfo=timezone.utc)
        applied_at = target.model_override_issued_at
        applied_at = applied_at if applied_at.tzinfo is not None else applied_at.replace(tzinfo=timezone.utc)
        if issued <= applied_at:
            status = "superseded"
    changed = False
    if status == "applied":
        if request["use_default"]:
            if target.model is not None or target.provider is not None or target.api_mode is not None:
                target.model = None
                target.provider = None
                target.api_mode = None
                changed = True
        else:
            for field_name in ("provider", "model", "api_mode"):
                value = request[field_name]
                if value is not None and getattr(target, field_name) != value:
                    setattr(target, field_name, value)
                    changed = True
        if changed:
            target.model_override_issued_at = issued_at or datetime.now(timezone.utc)
            store.save(target)
    default_provider = getattr(cfg, "default_provider", None)
    default_model = getattr(cfg, "default_model", None)
    data = {
        "ok": True,
        "status": status,
        "applied": status == "applied",
        "changed": changed,
        "scope": "agent_default",
        "cleared": bool(request["use_default"]) and status == "applied",
        "persona_id": persona_id,
        "applied_to_persona_id": str(target.id),
        "provider": target.provider,
        "model": target.model,
        "api_mode": target.api_mode,
        "default_provider": default_provider,
        "default_model": default_model,
        "effective_provider": target.provider or default_provider,
        "effective_model": target.model or default_model,
        "model_catalog_checked": False,
        "persistence": "agent_store",
        "warnings": request["warnings"],
        "next_expected": (
            "a newer model write already applied for this persona; refresh the Harness snapshot for current truth"
            if status == "superseded"
            else "refresh Harness snapshot; instances without their own override inherit this default live"
        ),
    }
    print(emit_json(data) if args.json else f"{status}: {target.id} model={data['effective_model']} provider={data['effective_provider']}")
    return 0


def _set_skills_error_payload(error_code: str, message: str, **identity) -> dict:
    return {
        "ok": False,
        "error_code": error_code,
        "error": safe_assignment_text(message, limit=320),
        "scope": "persona_template",
        **identity,
        "next_expected": "fix the arguments and retry; no persona skills were changed",
    }


def _validated_set_skills_request(args) -> dict:
    """Turn the argv into the set the template will hold — or refuse.

    **Absent is NEVER a write here.** ``--skill`` is ``default=None`` so the
    handler can tell "the operator listed skills" from "the operator listed
    none", and at THIS tier the second one has no meaning: the template is the
    root of the cascade, so there is nothing for an omitted flag to inherit
    from. Writing ``[]`` for it would turn any transport that dropped the
    repeated flag — a stale launcher build, a mangled argv, a capability whose
    ``allowedArgs`` lost a row — into a silent clear-every-skill. That exact
    collapse already shipped once at the instance tier (``list(args.skills or
    [])``; see THE BUG THIS REPLACES in ``_cmd_persona_instance_update_profile``)
    and cost every skill of every renamed agent. So absent is a typed
    ``nothing_to_write`` refusal, and emptying the set has its own flag.
    """

    raw_skills = list_flag_or_absent(args, "skills")
    clear = bool(getattr(args, "clear_skills", False))
    if raw_skills is not None and clear:
        raise _SetModelRequestError(
            "conflicting_args",
            "--clear-skills cannot be combined with --skill; pass one or the other",
        )
    if raw_skills is None and not clear:
        raise _SetModelRequestError(
            "nothing_to_write",
            "pass --skill (repeatable) to replace the persona's default skill set, or --clear-skills to empty it",
        )
    skills = [] if clear else _safe_skill_overrides([str(item) for item in raw_skills])
    if not clear and not skills:
        # Every id the operator supplied was dropped by token safety (or they
        # were all blank). Writing the survivors here would be an empty set —
        # i.e. the clear the previous branch just refused to infer — so it gets
        # the same answer rather than a different route to the same damage.
        raise _SetModelRequestError(
            "invalid_value",
            "every --skill value was rejected by token safety; pass --clear-skills to deliberately empty the set",
        )
    return {
        "skills": skills,
        "clear": clear,
        "issued_at": _parse_issued_at_arg(getattr(args, "issued_at", None)),
    }


def _cmd_persona_set_skills(args) -> int:
    """Persist a persona TEMPLATE's default skill set (profile-default tier).

    The skills half of ``persona set-model``, and deliberately its twin: same
    store-row write target (``_template_write_store_target``), same
    ``persona_not_persisted`` refusal for a config-only catalog id, same
    ``profile:<name>`` resolution, same supersede clock — on its OWN field
    (``skills_override_issued_at``), so a skills write and a model write can
    never supersede each other.

    Why the tier needs a verb at all: ``persona instance update-profile
    --skill`` writes ``skill_overrides`` on ONE agent, and a placement made
    later inherits ``persona.skills`` — not that agent's overrides. Before this
    verb no operator door wrote ``persona.skills``, so "set the skills, then
    place a new agent from that persona" could not work by construction.

    Inheritance is LIVE, not a copy: ``models.apply_instance_model_overrides``
    falls back to ``list(persona.skills)`` at EVERY resolution for an instance
    whose ``skill_overrides`` is ``None``. So this write also moves existing
    non-overridden instances, and the ack says that out loud instead of
    pretending only the future is affected — the first idle agent would
    disprove the pretence anyway.
    """

    cfg = load_agent_runtime_config()
    raw_id = str(getattr(args, "persona_id", "") or "").strip()
    try:
        persona = _persona_by_id(cfg, raw_id)
    except ValueError:
        persona = None
    if persona is None:
        # Root-observability on the REFUSAL, for the reason the create and retire
        # verbs carry it: a `persona_not_found` answered out of the WRONG runtime
        # root refuses exactly as plausibly as one out of the right one — and this
        # verb writes the template every later placement inherits.
        data = attach_root_observability({"ok": False, "error_code": "persona_not_found", "error": f"unknown persona: {safe_assignment_token(raw_id)}"})
        print(emit_json(data) if args.json else data["error"])
        return 2
    persona_id = str(getattr(persona, "id", "") or raw_id)
    try:
        request = _validated_set_skills_request(args)
    except _SetModelRequestError as exc:
        data = attach_root_observability(_set_skills_error_payload(exc.error_code, str(exc), persona_id=persona_id))
        print(emit_json(data) if args.json else data["error"])
        return 2
    store = AgentStore()
    target, refusal = _template_write_store_target(store, persona_id, what="persona default skills")
    if target is None:
        refusal = attach_root_observability(refusal)
        print(emit_json(refusal) if args.json else refusal["error"])
        return 2
    status = "applied"
    issued_at = request["issued_at"]
    if issued_at is not None and getattr(target, "skills_override_issued_at", None) is not None:
        issued = issued_at if issued_at.tzinfo is not None else issued_at.replace(tzinfo=timezone.utc)
        applied_at = target.skills_override_issued_at
        applied_at = applied_at if applied_at.tzinfo is not None else applied_at.replace(tzinfo=timezone.utc)
        if issued <= applied_at:
            status = "superseded"
    changed = False
    if status == "applied":
        requested = list(request["skills"])
        if list(target.skills or []) != requested:
            target.skills = requested
            changed = True
        if changed:
            target.skills_override_issued_at = issued_at or datetime.now(timezone.utc)
            store.save(target)
    stored_skills = list(target.skills or [])
    data = attach_root_observability({
        "ok": True,
        "status": status,
        "applied": status == "applied",
        "changed": changed,
        "scope": "persona_template",
        "cleared": bool(request["clear"]) and status == "applied",
        "persona_id": persona_id,
        "applied_to_persona_id": str(target.id),
        "skills": stored_skills,
        "unresolved": _unresolvable_skill_ids(stored_skills),
        "persistence": "agent_store",
        "next_expected": (
            "a newer skills write already applied for this persona; refresh the Harness snapshot for current truth"
            if status == "superseded"
            else "refresh Harness snapshot; instances whose skill_overrides is null follow this set live on their next resolution, and instances carrying their own overrides keep them"
        ),
    })
    print(emit_json(data) if args.json else f"{status}: {target.id} skills={','.join(stored_skills) or '(none)'}")
    return 0


def _unresolvable_skill_ids(skills: list[str]) -> list[str]:
    """Which of these ids no skills root on THIS machine can resolve.

    A WARNING, never a refusal (plan R3). The instance tier does not refuse
    them either; placement-time strictness already lives in the create verb's
    skills phase, and the readiness projection carries the standing truth for a
    template that names a skill this host lacks. Hard-gating here would make a
    realm-synced persona uneditable on any machine missing one of its skills.

    A resolver FAULT answers "nothing unresolved" rather than failing the verb:
    the store write has already landed by the time this runs, so a resolver
    problem must not turn a successful write into a non-zero exit.
    """

    if not skills:
        return []
    try:
        from agent_runtime.skill_resolution import resolve_skills

        resolutions = resolve_skills(list(skills))
    except Exception:  # noqa: BLE001 - advisory warning list, never a gate
        return []
    return [
        name
        for name in skills
        if str(getattr(resolutions.get(name), "status", "missing")) != "resolved"
    ]
