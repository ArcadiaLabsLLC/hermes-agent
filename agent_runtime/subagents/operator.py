"""Read children through the exact operator conversation and its recorded DB."""
from pathlib import Path
from dataclasses import dataclass

from agent_runtime import paths
from agent_runtime.live_turns import conversation_agents
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.operator_conversation import OperatorConversationRefused
from agent_runtime.operator_session_inspection import operator_session_read, inspection_identity, _inspection_persona
from agent_runtime.profile_context import resolve_persona_profile, persona_profile_scope, process_home_scope
from .model import HISTORY_OPERATIONS, SETTINGS_OPERATIONS, Refusal, SubagentError, include_service_capabilities
from .native import has_live_ancestor, inspect_records, registry_snapshot

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


def inspect_operator(operation: str, params: dict) -> dict:
    with operator_session_read(params) as (instance, session):
        binding = _subagent_profile_binding(instance)
        # An inherited profile is pinned to the conversation's recorded head,
        # not whichever profile a different turn temporarily exports to os.environ.
        home = (binding.profile_home or session.scope.head_home).resolve()
        identity = inspection_identity(params, session.owner)
        owner = (tuple(sorted(identity.items())), str(home), str(Path(session.db.db_path).resolve()))

        checked = _Owner(params, instance.id, session.db, home)
        if operation in HISTORY_OPERATIONS:
            from .history import inspect_history
            data = inspect_history(operation, params, owner=owner, db=session.db,
                                   session_id=params["session_id"], home=home, revalidate=checked.revalidate)
            return {**identity, **data}
        with persona_profile_scope(binding, runtime_root=paths.store_root()), process_home_scope(home):
            if operation in SETTINGS_OPERATIONS:
                from .settings import inspect_settings
                data = inspect_settings(operation, params, owner=owner,
                    profile_label=binding.hermes_profile or home.name, revalidate=checked.revalidate)
                return {**identity, **data}
            if operation in ("spawning", "spawning.set"):
                from .spawning import inspect_spawning
                data = inspect_spawning(operation, params, owner=owner,
                    host_kind="operator_runtime", revalidate=checked.revalidate)
                return {**identity, **data}
            records = [record for record in registry_snapshot() if checked.visible(record)]
            data = inspect_records(operation, params, owner=owner, visible=records,
                                   exact=checked.exact, revalidate=checked.revalidate, controllable=checked.controllable)
        return {**identity, **include_service_capabilities(operation, data)}
