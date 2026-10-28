"""``persona set-context``: a persona template's core-context-files and profile-memory switches.

Plan ``docs/agent-runtime-harness/planned/chat-lane-context-and-memory-gaps.md`` R1: both switches
(``AgentPersona.include_core_context_files`` / ``include_profile_memory``) were read every turn and
set only at create time, so an operator had to hand-edit a config file. This is the per-persona
setter; its wire twin is ``runtime.persona.set_context`` (``agent_runtime/serve_rpc/console_operations.py``).
The global default stays off. Every reply states what each switch costs, because both defaults are
deliberate: core context is a fixed per-turn prompt cost, profile memory is an identity inheritance.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_runtime.config import load_agent_runtime_config
from agent_runtime.operation_result import emit_operation_result
from agent_runtime.persona_assignments import safe_assignment_token
from agent_runtime.root_observability import attach_root_observability
from agent_runtime.store import AgentStore
from .chat_target import _persona_by_id
from .model_and_skills_commands import _template_write_store_target

__layer__ = "lanes"
__all__ = ["CONTEXT_SWITCHES", "SWITCH_COST", "_cmd_persona_set_context", "context_operation_result"]

#: request key -> the ``AgentPersona`` field it writes
CONTEXT_SWITCHES = {
    "core_context_files": "include_core_context_files",
    "profile_memory": "include_profile_memory",
}

#: what turning each switch ON costs, stated in every reply (plan R1 "Why the defaults are what they are")
SWITCH_COST = {
    "core_context_files": (
        "every turn carries the project context files (HERMES.md, the AGENTS.md chain, CLAUDE.md, "
        ".cursorrules) as a fixed prompt cost; a repo AGENTS.md alone can be ~16K tokens per turn"
    ),
    "profile_memory": (
        "every turn loads the bound profile's MEMORY.md and USER.md, so the persona inherits that "
        "profile's memory and its picture of who is who, not only its capabilities"
    ),
}


def _switch_value(raw, key: str):
    """``on``/``off`` (argv) or a bool (wire) -> bool; ``None`` when not given. Anything else refuses."""

    if raw is None or isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("on", "true"):
        return True
    if text in ("off", "false"):
        return False
    raise ValueError(key)


def _refusal(error_code: str, error: str, **identity) -> dict:
    return {"ok": False, "error_code": error_code, "error": error, "scope": "persona_template", **identity,
            "next_expected": "fix the arguments and retry; no context or memory switch was changed"}


def _cmd_persona_set_context(args) -> int:
    """Write one or both switches on a persona TEMPLATE (the store row the set-model verb writes).

    Instances read the template live, so the reply says the next turn of every agent placed from
    this persona follows it. Absent is never a write: a call naming neither switch refuses.
    """

    raw_id = str(getattr(args, "persona_id", "") or "").strip()
    try:
        # Each flag read by name, so the parser's dests have a reader the flag census can see.
        flags = {"core_context_files": getattr(args, "core_context_files", None),
                 "profile_memory": getattr(args, "profile_memory", None)}
        requested = {key: _switch_value(flags[key], key) for key in CONTEXT_SWITCHES}
    except ValueError as exc:
        data = attach_root_observability(_refusal(
            "invalid_value", f"--{str(exc).replace('_', '-')} takes on or off", persona_id=raw_id))
        emit_operation_result(args, data, data["error"])
        return 2
    try:
        persona = _persona_by_id(load_agent_runtime_config(), raw_id)
    except ValueError:
        persona = None
    if persona is None:
        data = attach_root_observability(_refusal(
            "persona_not_found", f"unknown persona: {safe_assignment_token(raw_id)}"))
        emit_operation_result(args, data, data["error"])
        return 2
    persona_id = str(getattr(persona, "id", "") or raw_id)
    given = {key: value for key, value in requested.items() if value is not None}
    if not given:
        data = attach_root_observability(_refusal(
            "nothing_to_write", "pass --core-context-files on|off and/or --profile-memory on|off",
            persona_id=persona_id))
        emit_operation_result(args, data, data["error"])
        return 2
    store = AgentStore()
    target, refusal = _template_write_store_target(store, persona_id, what="context and memory switches")
    if target is None:
        refusal = attach_root_observability(refusal)
        emit_operation_result(args, refusal, refusal["error"])
        return 2
    changed = [key for key, value in given.items() if bool(getattr(target, CONTEXT_SWITCHES[key])) != value]
    for key in changed:
        setattr(target, CONTEXT_SWITCHES[key], given[key])
    if changed:
        store.save(target)
    switches = {key: bool(getattr(target, field)) for key, field in CONTEXT_SWITCHES.items()}
    data = attach_root_observability({
        "ok": True,
        "status": "applied",
        "changed": changed,
        "scope": "persona_template",
        "persona_id": persona_id,
        "applied_to_persona_id": str(target.id),
        "switches": switches,
        # The cost of every switch that is ON after this write, so turning one on is never silent.
        "cost": {key: SWITCH_COST[key] for key, on in switches.items() if on},
        "persistence": "agent_store",
        "next_expected": "refresh Harness snapshot; every agent placed from this persona follows it on its next turn",
    })
    human = f"applied: {target.id} " + " ".join(f"{key}={'on' if on else 'off'}" for key, on in switches.items())
    emit_operation_result(args, data, human)
    return 0


def context_operation_result(params: dict) -> dict:
    """The wire twin's body: same validation and store as the CLI; no stdout capture."""

    rows: list[dict] = []
    args = SimpleNamespace(persona_id=params.get("persona_id"), json=True, operation_result_sink=rows.append,
                           **{key: params.get(key) for key in CONTEXT_SWITCHES})
    _cmd_persona_set_context(args)
    if len(rows) != 1:
        raise RuntimeError("context operation did not produce exactly one result")
    return rows[0]
