"""Native session binding for the existing read-only skills service, plus the worker half of lending.

``eternia.skills.{list,detail,history}`` read the addressed SESSION's catalog; with the child address
(``owner_scope`` + ``worker_generation`` + ``child_ref``, the ``eternia.subagents.*`` triple — all three or
none) they read the CHILD's: its working directory, its own tools, its own session's history. A stale
generation or a replaced worker is the subagent refusal (``subagent_reference_stale``), never a parent read.

``eternia.skills.lend`` (``mode: lend | revoke``) lends skills to a worker (p10-work §4, S2,
RT-ETERNIA-SKILLS-LENDS-SKILLS; RULED 2026-10-18: a write verb): every lent skill is resolved and checked
first (``skills_not_loadable`` with ``rejected_skills``; nothing written), then the ``skill_lends`` record,
then the child's compact-category seam attribute, then a steer announcing the change. The task half is the
serve's ``runtime.work.lend_skills``.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

__layer__ = "lanes"


_OPERATIONS = ("list", "detail", "history")
#: The child address on ``eternia.skills.*`` — the ``eternia.subagents.*`` read triple.
CHILD_PARAMS = ("owner_scope", "worker_generation", "child_ref")
LEND_MODES = ("lend", "revoke")
_STEER_LIMIT = 8192
_TASK_HALF = "runtime.work.lend_skills"


def declare_contracts() -> None:
    """The ``eternia.skills.*`` wire contracts (pydantic models), declared once per process.

    Under ``tui_gateway.pydantic_contracts: false`` nothing calls this at run time: the
    catalog generated from these same models (``agent_runtime/gateway/contract_catalog_data.py``)
    carries them, and ``scripts/gen_contract_catalog.py`` calls this to render them.
    """
    from tui_gateway.contracts import registry
    from tui_gateway.contracts.base import JsonValue, Result
    from tui_gateway.contracts.common import SessionParams

    names = ["eternia.skills." + operation for operation in (*_OPERATIONS, "lend")]
    if all(name in registry.METHODS for name in names):
        return

    class InspectParams(SessionParams):
        skill_id: str | None = None
        owner_scope: str | None = None
        worker_generation: str | None = None
        child_ref: str | None = None

    class LendParams(InspectParams):
        skills: list[str]
        mode: str = "lend"
        request_id: str

    class InspectResult(Result):
        data: dict[str, JsonValue]

    for name in names:
        if name not in registry.METHODS:
            registry.method(name, params=LendParams if name.endswith(".lend") else InspectParams,
                            result=InspectResult)


def _skills_error(rid, code: int, message: str, data: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message, **({"data": data} if data else {})}}


def _skills_invalid(rid, why: str) -> dict:
    return _skills_error(rid, 4090, "This skills request is invalid.", {"reason": "invalid_request", "detail": why})


def _child_of(params: dict) -> dict | None:
    """None for the session's own read; the LIVE child record for the full child address.

    Raises ``ValueError`` for a partial address and ``SubagentError`` for a stale or foreign child.
    """
    given = [key for key in CHILD_PARAMS if params.get(key) is not None]
    if not given:
        return None
    if len(given) != len(CHILD_PARAMS):
        raise ValueError("owner_scope, worker_generation and child_ref come together or not at all")
    from agent_runtime.subagents.native import child_record

    return child_record(params)


def _subagent_refusal(rid, exc) -> dict:
    from agent_runtime.subagents.model import ERROR_CODES

    return _skills_error(rid, ERROR_CODES[exc.reason], "Subagent inspection refused.", {"reason": exc.reason})


def _read_method(operation: str):
    from tui_gateway import server
    from agent_runtime.subagents.model import SubagentError

    def inspect(rid, params):
        snapshot = server.handle_request({"jsonrpc": "2.0", "id": rid,
            "method": "session.activate", "params": {
                "session_id": params["session_id"], "omit_messages": True}})
        if "error" in snapshot:
            return snapshot
        try:
            child = _child_of(params)
        except SubagentError as exc:
            return _subagent_refusal(rid, exc)
        except ValueError as exc:
            return _skills_invalid(rid, str(exc))
        try:
            with _bind_profile_home(params.get("profile")):
                data = _inspect(operation, snapshot["result"], params.get("skill_id"), child)
            if len(json.dumps(data, ensure_ascii=True)) > 900 * 1024:
                return _skills_error(rid, 4130, "This skill exceeds the document limit.")
            return {"jsonrpc": "2.0", "id": rid, "result": {"data": data}}
        except (OSError, ValueError):
            return _skills_error(rid, 4090, "Skill information is unavailable.")

    return inspect


def install() -> None:
    from tui_gateway import server
    from agent_runtime.gateway.contract_seam import pydantic_contracts_enabled

    if pydantic_contracts_enabled():
        declare_contracts()
    for operation in _OPERATIONS:
        server.register_method("eternia.skills." + operation, _read_method(operation))
    server.register_method("eternia.skills.lend", lend_method)


@contextmanager
def _bind_profile_home(profile: str | None) -> Iterator[None]:
    """The named profile's home for the read. A subprocess worker IS its profile (no
    ``profile`` param); the in-process worker names it on every request it sends."""
    if not profile:
        yield
        return
    from hermes_cli.profiles import get_profile_dir
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(get_profile_dir(profile))
    try:
        yield
    finally:
        reset_hermes_home_override(token)


def _reader_scope(snapshot: dict, child: dict | None) -> tuple[str, bool, str | None, bool]:
    """(cwd, can_load, history key, running) of the session read — or of the child's own agent."""
    info = snapshot["info"]
    if child is not None:
        agent = child["agent"]
        tools = getattr(agent, "valid_tool_names", None) or ()
        return (str(getattr(agent, "cwd", None) or info["cwd"]), "skill_view" in tools,
                getattr(agent, "session_id", None), True)
    tools = info.get("tools") or {}
    can_load = any("skill_view" in names for names in tools.values() if isinstance(names, list))
    key = snapshot.get("session_key") or info.get("stored_session_id") or snapshot.get("stored_session_id")
    return info["cwd"], can_load, key, bool(snapshot.get("running") or info.get("running"))


def _inspect(operation: str, snapshot: dict, skill_id: str | None, child: dict | None = None) -> dict:
    from agent.runtime_cwd import reset_session_cwd, set_session_cwd
    from agent_runtime import skill_activity
    from hermes_constants import get_hermes_home
    import hermes_state_registry
    from agent_runtime.skill_inspection import skill_inspection_reader

    cwd, can_load, key, running = _reader_scope(snapshot, child)
    token = set_session_cwd(cwd)
    try:
        reader = skill_inspection_reader()
        if operation == "list":
            lent = {} if child is None else {"lent": list(_lent_to_child(child))}
            return {"skills": reader.catalog(can_load=can_load), **lent}
        if operation == "detail":
            if not isinstance(skill_id, str) or not skill_id or len(skill_id) > 512:
                raise ValueError("invalid skill")
            return {"skill": reader.detail(skill_id, can_load=can_load)}
        if not key:
            return {"loaded": [], "historyComplete": False}
        db = hermes_state_registry.acquire(get_hermes_home() / "state.db")
        try:
            messages = db.get_messages_as_conversation(key, include_ancestors=True)
            return {"loaded": skill_activity.skill_load_history(messages), "historyComplete": not running}
        finally:
            hermes_state_registry.release_or_close(db)
    finally:
        reset_session_cwd(token)


# ── the worker half of lending ─────────────────────────────────────────────


def _lent_to_child(child: dict) -> tuple[str, ...]:
    from agent_runtime.skill_lends import child_target, lent_to

    return lent_to(child_target(str(child["subagent_id"])))


def _lend_request(params: dict) -> tuple[list[str], str, str]:
    skills, mode, request_id = params.get("skills"), params.get("mode") or "lend", params.get("request_id")
    if (not isinstance(skills, list) or not skills or len(skills) > 64
            or not all(isinstance(s, str) and s.strip() and len(s) <= 128 for s in skills)):
        raise ValueError("skills is a non-empty list of skill ids")
    if mode not in LEND_MODES:
        raise ValueError("mode is lend | revoke")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 120:
        raise ValueError("request_id is a string of at most 120 characters")
    return list(dict.fromkeys(s.strip() for s in skills)), mode, request_id


def _rescope(child: dict, lent: tuple[str, ...]) -> None:
    """The child's compact categories: its parent's kept set ∪ the lend (an unscoped parent stays unscoped).

    compact(keep) is "every category minus the kept ones", so compact(parent_keep ∪ lent) is the parent's
    compact set ∩ compact(lent); with nothing lent the child is back to its built state, unscoped.
    """
    from agent_runtime.chat_lane_skill_index import COMPACT_ATTR, compact_skill_categories

    owner = child.get("owner_session_record") or {}
    parent = owner.get("agent") if isinstance(owner, dict) else None
    scoped = getattr(parent, COMPACT_ATTR, None)
    if not isinstance(scoped, frozenset):
        return
    compact = scoped & compact_skill_categories(lent) if lent else frozenset()
    setattr(child["agent"], COMPACT_ATTR, compact)


def _announce(params: dict, request_id: str, mode: str, skills: list[str]) -> bool:
    from agent_runtime.subagents import native

    if mode == "lend":
        text = f"Skills lent: {', '.join(skills)}. Load one with skill_view(<id>) when it applies."
    else:
        text = f"Skills no longer lent: {', '.join(skills)}. A body already loaded stays until the turn ends."
    return native.steer_child(params, text.encode("utf-8")[:_STEER_LIMIT].decode("utf-8", "ignore"),
                              f"lend:{request_id}") == "queued"


def lend_method(rid, params):
    """``eternia.skills.lend``: lend skills to (or revoke them from) the child the address names."""
    from agent_runtime.chat_verbs import queue_skill
    from agent_runtime import skill_lends
    from agent_runtime.subagents.model import SubagentError
    from agent_runtime.subagents.native import child_registered

    if all(params.get(key) is None for key in CHILD_PARAMS):
        return _skills_invalid(rid, f"lend names a child (owner_scope, worker_generation, child_ref); a task's is {_TASK_HALF}")
    try:
        skills, mode, request_id = _lend_request(params)
        child = _child_of(params)
    except SubagentError as exc:
        return _subagent_refusal(rid, exc)
    except ValueError as exc:
        return _skills_invalid(rid, str(exc))
    try:
        with _bind_profile_home(params.get("profile")):
            rejected = queue_skill._rejected_skills(skills) if mode == "lend" else {}
            if rejected:
                return _skills_error(rid, 4090, "One or more skills are not loadable.",
                              {"reason": "skills_not_loadable", "rejected_skills": rejected})
            target = skill_lends.child_target(str(child["subagent_id"]))
            if mode == "lend":
                skill_lends.lend(target, skills, owner_session=str(params["session_id"]), by=str(params["session_id"]))
            else:
                skill_lends.revoke(target, skills)
            lent = skill_lends.lent_to(target)
            _rescope(child, lent)
            skill_lends.sweep(child_registered)
        steered = _announce(params, request_id, mode, skills)
    except SubagentError as exc:
        return _subagent_refusal(rid, exc)
    except (OSError, ValueError):
        return _skills_error(rid, 4090, "The lend could not be recorded.")
    return {"jsonrpc": "2.0", "id": rid, "result": {"data": {
        "target": target, "skills_lent": list(lent), "effective": "next_turn", "steered": steered}}}


__all__ = ["CHILD_PARAMS", "LEND_MODES", "declare_contracts", "install", "lend_method"]
