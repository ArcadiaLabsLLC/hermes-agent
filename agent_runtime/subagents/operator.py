"""Read children through the exact operator conversation and its recorded DB."""
from pathlib import Path
from dataclasses import dataclass

from agent_runtime import paths
from agent_runtime.live_turns import conversation_agents
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.operator_conversation import OperatorConversationRefused
from agent_runtime.operator_session_inspection import operator_session_read, inspection_identity, _inspection_persona
from agent_runtime.profile_context import resolve_persona_profile, persona_profile_context
from .model import (HISTORY_OPERATIONS, SETTINGS_OPERATIONS, SPAWNING_OPERATIONS, Refusal, SubagentError,
                    include_history_capabilities, validate_request)
from .native import has_live_ancestor, inspect_records, registry_snapshot
from .references import references

__layer__ = "lanes"


def _belongs(record, db, session_id, home):
    """Use the actual child's captured home and DB, never ambient profile state."""
    agent = record.get("agent")
    db_path = getattr(getattr(agent, "_session_db", None), "db_path", None)
    logs_dir = getattr(agent, "logs_dir", None)
    durable_owner = record.get("owner_agent_session_id")
    if (record.get("owner_session_record") is not None or not db_path or
            not logs_dir or not durable_owner):
        return False
    if Path(db_path).resolve() != Path(db.db_path).resolve() or Path(logs_dir).resolve().parent != home:
        return False
    # Resolve only ids that actually exist in this owner's database. Unknown
    # identities cannot become authority through a best-effort resolver fallback.
    if db.get_session(durable_owner) is None:
        return False
    owned_tip = db.resolve_resume_session_id(durable_owner)
    requested_tip = db.resolve_resume_session_id(session_id)
    return bool(owned_tip and requested_tip and owned_tip == requested_tip)


def _subagent_profile_binding(instance):
    persona = _inspection_persona(instance, load_agent_runtime_config())
    binding = resolve_persona_profile(persona)
    if binding.readiness != "ready":
        raise OperatorConversationRefused("profile_unavailable")
    return binding


@dataclass
class _Owner:
    params: dict
    instance_id: str
    db: object
    home: Path

    def visible(self, record):
        return _belongs(record, self.db, self.params["session_id"], self.home)

    def exact(self, record):
        parents = conversation_agents(self.params["session_id"], self.instance_id)
        return self.visible(record) and has_live_ancestor(record, parents)

    def controllable(self, record):
        parents = conversation_agents(self.params["session_id"], self.instance_id)
        return bool(parents) and self.visible(record) and has_live_ancestor(record, parents)

    def revalidate(self):
        with operator_session_read(self.params) as (instance, session):
            binding = _subagent_profile_binding(instance)
            if ((binding.profile_home or session.scope.head_home).resolve() != self.home or
                    Path(session.db.db_path).resolve() != Path(self.db.db_path).resolve()):
                raise SubagentError(Refusal.WRONG_OWNER)


def _operator_owner(params, instance, session):
    """(binding, home, identity, owner) of the exact operator conversation's children."""
    binding = _subagent_profile_binding(instance)
    # An inherited profile is pinned to the conversation's recorded head,
    # not whichever profile a different turn temporarily exports to os.environ.
    home = (binding.profile_home or session.scope.head_home).resolve()
    identity = inspection_identity(params, session.owner)
    owner = (tuple(sorted(identity.items())), str(home), str(Path(session.db.db_path).resolve()))
    return binding, home, identity, owner


def inspect_operator(operation: str, params: dict) -> dict:
    with operator_session_read(params) as (instance, session):
        binding, home, identity, owner = _operator_owner(params, instance, session)

        if operation in SETTINGS_OPERATIONS:
            from .settings import inspect_settings
            return {**identity, **inspect_settings(operation, params, owner=owner, home=home)}
        if operation in SPAWNING_OPERATIONS:
            # Operator turns run delegate_task in the serve itself: the pause is serve-wide.
            from .spawning import inspect_spawning
            validate_request(operation, params)
            generation = references.require_generation(owner, params.get("expected_generation"))
            return {**identity, **inspect_spawning(operation, params, generation=generation,
                                                   host_kind="operator_runtime")}
        checked = _Owner(params, instance.id, session.db, home)
        if operation in HISTORY_OPERATIONS:
            from .history import inspect_history
            data = inspect_history(operation, params, owner=owner, db=session.db,
                                   session_id=params["session_id"], home=home, revalidate=checked.revalidate)
            return {**identity, **data}
        with persona_profile_context(binding, runtime_root=paths.store_root()):
            records = [record for record in registry_snapshot() if checked.visible(record)]
            data = inspect_records(operation, params, owner=owner, visible=records,
                                   exact=checked.exact, revalidate=checked.revalidate, controllable=checked.controllable)
        return {**identity, **include_history_capabilities(operation, data)}


def inspect_operator_child_skills(operation: str, params: dict) -> dict:
    """``runtime.operator.conversation.skills`` on the child ``child_ref`` names (RT-SERVE-SKILLS-OPERATOR-CHILD-ADDRESS).

    The ``child_ref`` is the one ``runtime.operator.conversation.subagents.list`` minted for this exact
    conversation, so the same owner derivation resolves it here; a replaced or foreign child is
    ``subagent_reference_stale``, never the parent's catalog. ``list`` / ``detail`` / ``history`` read the
    child's own working directory, tools and session; ``lend`` (``skills``, ``mode: lend | revoke``,
    ``request_id``) writes the child's lend and steers it, the worker lane's ``eternia.skills.lend`` in-serve.
    """
    from agent_runtime import skill_activity
    from agent_runtime.skill_inspection import SkillInspectionError
    from agent_runtime.conversations.worker_skills import (
        child_reader_scope, lend_announcement, lend_request, read_skills, record_lend,
    )
    from .commands import control_records
    from .native import _named_child, still_registered

    child_ref = params.get("child_ref")
    if not isinstance(child_ref, str) or not child_ref or len(child_ref) > 512:
        raise SubagentError(Refusal.INVALID)
    try:
        lend = lend_request(params) if operation == "lend" else None
    except ValueError as exc:
        raise OperatorConversationRefused("invalid_lend_request") from exc
    with operator_session_read(params) as (instance, session):
        binding, home, identity, owner = _operator_owner(params, instance, session)
        checked = _Owner(params, instance.id, session.db, home)
        with persona_profile_context(binding, runtime_root=paths.store_root()):
            records = [record for record in registry_snapshot()
                       if checked.visible(record) and still_registered(record)]
            child = _named_child(owner, records, checked.exact, child_ref)
            if lend is None:
                cwd, can_load, key = child_reader_scope(child, session.row.get("cwd"))

                def history() -> dict:
                    # A live child is running: its history is never complete.
                    messages = session.db.get_messages_as_conversation(key, include_ancestors=True) if key else []
                    return {"loaded": skill_activity.skill_load_history(messages), "historyComplete": False}

                try:
                    data = read_skills(operation, cwd=cwd, can_load=can_load, skill_id=params.get("skill_id"),
                                       history=history, child=child)
                except SkillInspectionError:
                    raise
                except ValueError as exc:
                    raise OperatorConversationRefused("invalid_skill_id") from exc
                checked.revalidate()
                return {**identity, "child_ref": child_ref, **data}
            skills, mode, request_id = lend
            try:
                target, lent = record_lend(child, skills, mode, owner_session=params["session_id"])
            except OSError as exc:
                raise SubagentError(Refusal.UNKNOWN) from exc
        try:
            steer = control_records("steer", {"child_ref": child_ref, "request_id": f"lend:{request_id}",
                                              "text": lend_announcement(mode, skills)},
                                    owner=owner, records=records, exact=checked.exact, revalidate=checked.revalidate)
        except SubagentError:  # the lend is written; only the announcement did not reach the child
            steer = {}
        return {**identity, "child_ref": child_ref, "target": target, "skills_lent": list(lent),
                "effective": "next_turn", "steered": steer.get("status") == "queued"}
