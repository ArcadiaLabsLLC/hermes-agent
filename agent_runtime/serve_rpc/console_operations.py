"""Native twins of the Agent Console's local operations, behind existing owners."""
from functools import partial

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from .protocol import err, ok, defer_or_inline, ERR_INVALID_PARAMS, ERR_NOT_FOUND, ERR_CONFLICT
from .registry import method
from agent_runtime.param_readers import read_text
__layer__ = "lanes"


def _value_error(key: str, sentence: str) -> ValueError:
    return ValueError(key)


_console_text = partial(read_text, refuse=_value_error)


def _operation(rid, params, context, name, run):
    def execute():
        try:
            result = run(params)
            if result.get("ok") is False:
                return err(rid, ERR_CONFLICT, "The operation was refused.", result)
            import json
            if len(json.dumps(result, ensure_ascii=True)) > 900 * 1024:
                return err(rid, 4130, "This information is too large to display.",
                           {"reason": "response_too_large"})
            return ok(rid, result)
        except ValueError as exc:
            return err(rid, ERR_INVALID_PARAMS, "Invalid operation parameters.",
                       {"reason": "invalid_parameters", "field": str(exc)})
        except Exception as exc:
            return err(rid, ERR_CONFLICT, "The operation could not complete.",
                       {"reason": "operation_failed", "error_class": type(exc).__name__})
    return defer_or_inline(rid, name, context, execute)


def _console_model(params, instance):
    from hermes_cli.harness_parts.persona.model_and_skills_commands import model_operation_result
    _console_text(params, "persona_instance_id" if instance else "persona_id", required=True)
    for key in ("model", "provider", "reasoning_effort", "issued_at"):
        _console_text(params, key)
    if "use_default" in params and type(params["use_default"]) is not bool:
        raise ValueError("use_default")
    return model_operation_result(params, instance=instance)


@method("runtime.persona.instance.set_model", tier=TIER_CONSOLE)
def instance_model(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.instance.set_model", lambda p: _console_model(p, True))


@method("runtime.persona.set_model", tier=TIER_CONSOLE)
def persona_model(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.set_model", lambda p: _console_model(p, False))


def _context_switches(params):
    from hermes_cli.harness_parts.persona.context_memory_commands import CONTEXT_SWITCHES, context_operation_result
    _console_text(params, "persona_id", required=True)
    for key in CONTEXT_SWITCHES:
        if params.get(key) is not None and type(params[key]) is not bool:
            raise ValueError(key)
    return context_operation_result(params)


@method("runtime.persona.set_context", tier=TIER_CONSOLE)
def persona_context(rid, params, context=None):
    """Plan chat-lane-context-and-memory-gaps R1: ``persona set-context``'s wire twin."""
    return _operation(rid, params, context, "runtime.persona.set_context", _context_switches)


def _permission(params, preview):
    from hermes_cli.harness_parts.persona.inspect_commands import permission_operation_result
    for key in ("persona_id", "session_id"):
        _console_text(params, key, required=True)
    _console_text(params, "reason", required=not preview)
    _console_text(params, "expires_at")
    if params.get("mode") not in ("profile_default", "bounded", "read_only", "unbounded"):
        raise ValueError("mode")
    for key in ("ttl_seconds", "turns"):
        if params.get(key) is not None and (type(params[key]) is not int or params[key] < 1):
            raise ValueError(key)
    return permission_operation_result(params, preview=preview)


@method("runtime.persona.permission.preview", tier=TIER_CONSOLE)
def permission_preview(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.permission.preview", lambda p: _permission(p, True))


@method("runtime.persona.permission.set", tier=TIER_CONSOLE)
def permission_set(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.permission.set", lambda p: _permission(p, False))


@method("runtime.prompt_context.show", tier=TIER_CONSOLE)
def prompt_context(rid, params, context=None):
    def read(p):
        from agent_runtime.prompt_observability import load_persisted_context_row
        _console_text(p, "context_id", required=True)
        result = load_persisted_context_row(p["context_id"])
        if result is None:
            return {"found": False, "context_id": p["context_id"]}
        return result
    return _operation(rid, params, context, "runtime.prompt_context.show", read)


@method("runtime.persona.instance.detail", tier=TIER_READ)
def instance_detail(rid, params, context=None):
    def read(p):
        from agent_runtime.snapshot.details import persona_instance_detail_for_id
        _console_text(p, "instance_id", required=True)
        result = persona_instance_detail_for_id(p["instance_id"])
        return result if result is not None else {"found": False, "instance_id": p["instance_id"]}
    return _operation(rid, params, context, "runtime.persona.instance.detail", read)


@method("runtime.skills.catalog", tier=TIER_READ)
def skills_catalog(rid, params, context=None):
    def read(p):
        from agent_runtime.prompt_observability import skills_catalog_by_hash
        from agent_runtime.snapshot.build import build_snapshot
        _console_text(p, "content_hash", required=True)
        result = skills_catalog_by_hash(p["content_hash"], materialize=build_snapshot)
        return {"hash": p["content_hash"], "found": result is not None, "skills": result or []}
    return _operation(rid, params, context, "runtime.skills.catalog", read)


def _toolset_persona(params):
    """The persona ``params["persona_id"]`` names, or ``None`` when the store has none."""
    from agent_runtime.store import AgentStore
    try:
        return AgentStore().get(params["persona_id"])
    except (FileNotFoundError, KeyError):
        return None


def _toolset_approve(params):
    """Grant or revoke one persona's opt-in to a bundled-disabled toolset (``agent_runtime/bundled_toolsets``).

    The bundled edition writes the record; the Developer Edition answers ``edition_not_bundled``. A typed
    refusal is ``data.reason``; the reply carries the persona's ``toolset_approvals`` after the write."""
    import logging

    from agent_runtime import bundled_toolsets as bt
    for key in ("persona_id", "toolset"):
        _console_text(params, key, required=True)
    _console_text(params, "reason")
    if params.get("mode") not in tuple(bt.Mode):
        raise ValueError("mode")
    persona = _toolset_persona(params)
    if persona is None:
        return {"ok": False, "reason": "persona_not_found", "persona_id": params["persona_id"]}
    home = bt.persona_home(persona)
    try:
        bt.write_approval(home, params["toolset"], mode=params["mode"], reason=params.get("reason") or "",
                          granted_by="operator")
    except bt.ToolsetApprovalRefused as refused:
        return {"ok": False, "reason": refused.reason.value, "toolset": params["toolset"]}
    logging.getLogger(__name__).info("persona.toolset_approved persona_id=%s toolset=%s mode=%s",
                                     params["persona_id"], params["toolset"], params["mode"])
    return {"persona_id": params["persona_id"], "toolset": params["toolset"], "mode": params["mode"],
            "toolset_approvals": [str(row["toolset"]) for row in bt.read_approvals(home)]}


@method("runtime.persona.toolset.approve", tier=TIER_CONSOLE)
def toolset_approve(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.toolset.approve", _toolset_approve)


def _toolset_list(params):
    """The opt-in toolsets this edition offers one persona, each granted or not (the approve verb's read).

    The Developer Edition offers none and says so with ``edition_not_bundled: true``; an unknown persona
    is the approve verb's ``persona_not_found`` refusal."""
    from agent_runtime import bundled_toolsets as bt
    _console_text(params, "persona_id", required=True)
    persona = _toolset_persona(params)
    if persona is None:
        return {"ok": False, "reason": "persona_not_found", "persona_id": params["persona_id"]}
    bundled = bt.edition_bundled()
    offers = bt.toolset_offers(bt.persona_home(persona)) if bundled else ()
    return {"persona_id": params["persona_id"], "edition_not_bundled": not bundled, "toolsets": list(offers)}


@method("runtime.persona.toolset.list", tier=TIER_CONSOLE)
def toolset_list(rid, params, context=None):
    return _operation(rid, params, context, "runtime.persona.toolset.list", _toolset_list)
