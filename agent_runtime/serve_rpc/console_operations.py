"""Native twins of the Agent Console's local operations, behind existing owners."""
from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from .protocol import err, ok, deferred_reply, DEFERRED, ERR_INVALID_PARAMS, ERR_NOT_FOUND, ERR_CONFLICT
from .registry import method
__layer__ = "lanes"


def _console_text(params, key, *, required=False):
    value = params.get(key)
    if value is None and not required:
        return
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(key)


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
    build = deferred_reply(rid, name, execute)
    if context is not None and context.spawn_reply is not None and context.spawn_reply(build):
        return DEFERRED
    return build()


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
