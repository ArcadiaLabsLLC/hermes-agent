"""Host-selected runtime and Mission Control participant resolution."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from agent_runtime.resolution import resolve_runtime, runtime_resolution_scope
from agent_runtime.errors import NotFound
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from agent_runtime.profile_home import (
    record_hermes_head_home_if_unset, reset_hermes_head_home, get_hermes_head_home,
)
from .definitions import ParticipantRef
from .run_values import DiscussionError
from .app_functions import DiscussionAppFunctions

__layer__ = "stores"


class NativeContext:
    """Captured by the socket-owning serve, never from client parameters."""
    def __init__(self, root: Path, home: Path, install_id: str,
                 *, invoke: Callable[[Any], int] | None = None) -> None:
        self.root, self.home, self.install_id = root.resolve(), home.resolve(), install_id
        self.resolution = resolve_runtime({"HERMES_AGENT_RUNTIME_ROOT": str(self.root), "HERMES_HOME": str(self.home)})
        self.invoke = invoke or _invoke_native
        self.launcher = DiscussionAppFunctions()

    @contextmanager
    def scope(self) -> Iterator[None]:
        home_token = set_hermes_home_override(self.home)
        head_token = record_hermes_head_home_if_unset(self.home)
        try:
            if get_hermes_head_home().resolve() != self.home:
                raise DiscussionError("runtime_home_mismatch")
            with runtime_resolution_scope(self.resolution):
                yield
        finally:
            reset_hermes_head_home(head_token)
            reset_hermes_home_override(home_token)

    def workspaces(self) -> list[dict[str, str]]:
        from agent_runtime.store import WorkspaceStore
        with self.scope():
            rows = WorkspaceStore().list_all()
            if len(rows) > 10000:
                raise DiscussionError("workspace_catalog_limit")
            return [{"id": row.id, "name": row.name} for row in rows]

    def workspace(self, workspace_id: str):
        from agent_runtime.store import WorkspaceStore
        with self.scope():
            try:
                workspace = WorkspaceStore().get(workspace_id)
            except (KeyError, FileNotFoundError, NotFound) as exc:
                raise DiscussionError("workspace_not_found") from exc
            if workspace.archived:
                raise DiscussionError("workspace_archived")
            return workspace

    def resolve(self, ref: ParticipantRef, workspace_id: str, *,
                require_placement: bool = True, require_ready: bool = True) -> dict[str, Any]:
        from agent_runtime.persona_assignments import PersonaInstanceStore
        from agent_runtime.config import load_agent_runtime_config, ensure_persisted_personas
        from agent_runtime.profile_context import resolve_persona_profile, active_profile_name
        from agent_runtime.workspace_scope import effective_workspace_id
        from agent_runtime.persona_lifecycle import is_runtime_persona

        if ref.install_id != self.install_id:
            raise DiscussionError("remote_members_not_supported")
        with self.scope():
            self.workspace(workspace_id)
            store = PersonaInstanceStore()
            try:
                instance = store.get(ref.instance_id)
            except (KeyError, FileNotFoundError, NotFound) as exc:
                raise DiscussionError("instance_not_found", instance_id=ref.instance_id) from exc
            if store.retired_instance_archive_path(ref.instance_id, persona_id=instance.persona_id) is not None:
                raise DiscussionError("instance_retired", instance_id=ref.instance_id)
            if require_placement and effective_workspace_id(instance, active_workspace_id=workspace_id) != workspace_id:
                raise DiscussionError("foreign_workspace", instance_id=ref.instance_id)
            personas = {p.id: p for p in ensure_persisted_personas(load_agent_runtime_config())}
            persona = personas.get(instance.persona_id)
            if persona is None or not is_runtime_persona(persona):
                raise DiscussionError("persona_not_found", instance_id=ref.instance_id)
            binding = resolve_persona_profile(persona)
            if require_ready and binding.readiness != "ready":
                raise DiscussionError("profile_unavailable", instance_id=ref.instance_id)
            return {**ref.to_dict(), "persona_id": instance.persona_id,
                    "profile": binding.hermes_profile or active_profile_name(),
                    "display_name": instance.display_name}

    def resolve_room(self, ref: ParticipantRef, workspace_id: str) -> dict[str, Any]:
        """Explicit room membership does not move an agent or require its profile online."""
        return self.resolve(ref, workspace_id, require_placement=False, require_ready=False)

    def resolve_member(self, run: Mapping[str, Any], member: Mapping[str, Any]) -> dict[str, Any]:
        return self.resolve(ParticipantRef(member["install_id"], member["instance_id"]),
                            run["workspace_id"], require_placement=run["table_id"] is not None)

    def roster(self, workspace_id: str) -> list[dict[str, Any]]:
        from agent_runtime.persona_assignments import PersonaInstanceStore
        with self.scope():
            self.workspace(workspace_id)
            result = []
            scan = PersonaInstanceStore().scan_all()
            if scan.unreadable:
                raise DiscussionError("roster_unreadable", count=scan.unreadable)
            if len(scan.instances) > 1024:
                raise DiscussionError("roster_limit", count=len(scan.instances))
            for instance in scan.instances:
                ref = ParticipantRef(self.install_id, instance.id)
                try:
                    row = self.resolve(ref, workspace_id)
                    row.update(available=True, reason=None)
                except DiscussionError as exc:
                    if exc.reason == "foreign_workspace":
                        continue
                    row = {**ref.to_dict(), "display_name": instance.display_name,
                           "persona_id": instance.persona_id, "profile": instance.profile_id,
                           "available": False, "reason": exc.reason}
                result.append(row)
            return result

    def ensure_session(self, run: Mapping[str, Any], member: Mapping[str, Any]) -> None:
        from hermes_state import SessionDB
        from agent_runtime.persona_chat_durability import ensure_persona_chat_session
        with self.scope():
            db = SessionDB(db_path=self.home / "state.db")
            try:
                existing = db.get_session(member["session_id"])
                if existing is not None:
                    import json
                    config = existing.get("model_config") or {}
                    if isinstance(config, str):
                        config = json.loads(config)
                    if (config.get("persona_instance_id"), config.get("persona_id")) != (member["instance_id"], member["persona_id"]):
                        raise DiscussionError("session_owner_conflict")
                ensure_persona_chat_session(session_db=db, session_id=member["session_id"],
                    persona_id=member["persona_id"], title=f"Discussion {run['run_id'][-8:]} · {member['handle']}", required=True)
                db.set_session_hidden(member["session_id"], True)
            finally:
                db.close()

    def journal(self, session_id: str, native_id: str) -> dict[str, Any] | None:
        from agent_runtime.mission_chat_turns import mission_chat_turn_record
        with self.scope():
            return mission_chat_turn_record(session_id=session_id, client_message_id=native_id)


def _invoke_native(args: Any) -> int:
    """One turn through the mission-chat door (ruling Q10) — never the CLI
    namespace. The door installs its own sink, so the last payload is handed
    on to the worker's; an unbound door raises ``MissionChatDoorUnbound``."""
    from agent_runtime.mission_chat_door import run_mission_chat_turn
    sink = args.payload_sink
    code, payload = run_mission_chat_turn(args)
    if payload is not None:
        sink(payload)
    return code
