"""Adopt a saved local Compare into one native Discussion, without executing history."""
from __future__ import annotations

from agent_runtime.conversation_owner import client_scope, ConversationOwnerError
from agent_runtime.conversations.model import ConversationScope
from agent_runtime.conversations.migration import migration_target
from gateway import hosted_rooms as rooms
from . import compare_archive as archive
from . import compare_import_store as store
from .definitions import DiscussionSettings, ParticipantRef
from .room_definition import RoomSpec
from .room_owner import room_client_scope, scoped_room_key
from .run_admission import Admission, admit
from .run_values import DiscussionError, digest, member_id

__layer__ = "lanes"


def _owner(params):
    try:
        owner = client_scope(params.get("client_scope"))
    except ConversationOwnerError as exc:
        raise DiscussionError(exc.reason) from exc
    if owner is None:
        raise DiscussionError("conversation_owner_changed")
    return owner


def _key(source_id, owner):
    return scoped_room_key("compare-import:" + digest({"source": source_id}), owner)


def _owned(service, params, actor_id):
    run = service.runs.get(params["run_id"], params["workspace_id"])
    if room_client_scope(run) != _owner(params) or run["actor_id"] != actor_id:
        raise DiscussionError("conversation_owner_changed")
    if "compare_import" not in run["initial"]:
        raise DiscussionError("compare_import_required")
    return run


def resolve_compare(service, params, actor_id):
    run = store.find(service.runs, _owner(params), actor_id, params["source_id"])
    return {"run": run}


def _targets(service, source, workspace, owner, actor_id):
    conversations = service.executions.profiles.turns.conversations()
    result = {}
    for row in source["members"]:
        ref = ParticipantRef.parse(row["participant"])
        live = service.context.resolve_room(ref, workspace)
        scope = ConversationScope(actor_id, owner, row["profile"])
        target = migration_target(scope, {"persona_id": live["persona_id"], "persona_instance_id": ref.instance_id})
        if live["profile"] != row["profile"]:
            raise DiscussionError("profile_binding_changed")
        if row["session_id"] is not None:
            conversations._owned_route(scope, row["session_id"])
        result[member_id(ref)] = (row, scope, target)
    return conversations, result


def prepare_compare(service, params, actor_id):
    owner, source, workspace = _owner(params), params["source"], params["workspace_id"]
    with service._lock, service.context.scope():
        if not service.accepting:
            raise DiscussionError("runtime_stopping")
        previous = store.find(service.runs, owner, actor_id, source["id"])
        if previous is not None:
            if previous["workspace_id"] != workspace or previous["initial"]["compare_import"]["source"] != source:
                raise DiscussionError("migration_target_changed")
            if previous["initial"]["compare_import"]["state"] == "pending":
                _ensure_history_room(service, previous)
            return {"run": previous}
        _targets(service, source, workspace, owner, actor_id)
        refs = tuple(ParticipantRef.parse(row["participant"]) for row in source["members"])
        spec = RoomSpec(source["name"], refs, DiscussionSettings(1, True, False, None))
        initial = {"discussion": spec.to_dict(), "client_scope": owner,
                   "compare_import": {"state": "pending", "source": source}}
        admission = Admission(initial, refs, {ref: index for index, ref in enumerate(refs)})
        run = admit(service.runs.connect, workspace, key=_key(source["id"], owner), topic="", actor_id=actor_id,
            identity=initial, load=lambda _conn: admission, resolve=service.context.resolve_room, allow_empty_topic=True)
        if run["actor_id"] != actor_id:
            raise DiscussionError("conversation_owner_changed")
        _ensure_history_room(service, run)
        return {"run": run}


def _ensure_history_room(service, run):
    rooms.create_room(service.db_path, room_id=run["run_id"], name=run["initial"]["discussion"]["name"],
        members=service.state.roster(service.runs.members(run["run_id"])), authority_gateway_id=service.context.install_id)


def append_compare(service, params, actor_id):
    with service._lock:
        run = _owned(service, params, actor_id)
        if run["initial"]["compare_import"]["state"] == "complete":
            raise DiscussionError("archive_sealed")
        archive.append_chunk(service, run, params["index"], params["data"])
        return {"run": run}


def finish_compare(service, params, actor_id):
    with service._lock, service.context.scope():
        if not service.accepting:
            raise DiscussionError("runtime_stopping")
        run = _owned(service, params, actor_id)
        if run["initial"]["compare_import"]["state"] == "complete":
            return {"run": run}
        archive.read_archive(service, run)
        source = run["initial"]["compare_import"]["source"]
        conversations, targets = _targets(service, source, run["workspace_id"], _owner(params), actor_id)
        sessions = {}
        for member in service.runs.members(run["run_id"]):
            row, scope, target = targets[member["member_id"]]
            session = member["session_id"]
            if row["session_id"] is not None:
                session = conversations.migrate(scope, row["session_id"],
                    {"persona_id": target.persona_id, "persona_instance_id": target.id})["session_id"]
            service.context.ensure_session(run, {**member, "session_id": session})
            sessions[member["member_id"]] = session
        _targets(service, source, run["workspace_id"], _owner(params), actor_id)
        return {"run": store.complete(service.runs, run, sessions)}
