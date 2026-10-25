"""Explicit adoption of a paused profile group into its existing native room.

The run's durable intent fences commands across crashes. Each member reuses the
Direct migration receipt; only after every import succeeds do all bindings change
in one transaction. No public event is copied, rewritten or scheduled by adoption.
"""
from __future__ import annotations

from pathlib import Path

from agent_runtime.conversation_owner import client_scope, ConversationOwnerError
from agent_runtime.conversations.migration import migration_target
from .definitions import DiscussionSettings, ParticipantRef
from .profile_groups import member_scope
from .room_definition import RoomSpec
from .room_owner import room_client_scope
from .run_values import DiscussionError
from . import group_migration_store as store

__layer__ = "lanes"


def _prepare(service, run, intent, conversations):
    members = service.runs.members(run["run_id"])
    targets = {row["member_id"]: row["participant"] for row in intent["members"]}
    if set(targets) != {m["member_id"] for m in members}:
        raise DiscussionError("migration_members_changed")
    if run["phase"] != "paused" or service.state.unresolved(run["run_id"]):
        raise DiscussionError("pause_before_migration")
    resolved = {}
    for member in members:
        scope = member_scope(run, member)
        live = service.context.resolve_room(ParticipantRef.parse(targets[member["member_id"]]), intent["target_workspace_id"])
        params = {"persona_id": live["persona_id"], "persona_instance_id": live["instance_id"]}
        target = migration_target(scope, params)
        home = conversations.profile_home(scope.profile).resolve(strict=True)
        if live["profile"] != member["profile"] or home != Path(member["binding"]["home"]).resolve(strict=True):
            raise DiscussionError("profile_binding_changed")
        resolved[member["member_id"]] = (scope, target)
    return members, resolved


def migrate_group(service, params, actor_id):
    try:
        owner = client_scope(params.get("client_scope"))
    except ConversationOwnerError as exc:
        raise DiscussionError(exc.reason) from exc
    if owner is None:
        raise DiscussionError("conversation_owner_changed")
    intent = {"target_workspace_id": params["target_workspace_id"], "members": params["members"]}
    with service._lock, service.context.scope():
        if not service.accepting:
            raise DiscussionError("runtime_stopping")
        run = service.runs.get(params["run_id"], params["workspace_id"])
        if room_client_scope(run) != owner or run["actor_id"] != actor_id:
            raise DiscussionError("conversation_owner_changed")
        previous = run["initial"].get("group_migration")
        if previous is not None and previous["intent"] != intent:
            raise DiscussionError("migration_target_changed")
        if previous is not None and previous["state"] == "complete":
            return {"run": run}
        if "group" not in run["initial"]:
            raise DiscussionError("profile_group_required")
        service.context.workspace(intent["target_workspace_id"])
        conversations = service.executions.profiles.turns.conversations()
        members, resolved = _prepare(service, run, intent, conversations)
        run = store.reserve(service.runs, run, intent, params["expect_revision"])
        adopted = {}
        for member in members:
            scope, target = resolved[member["member_id"]]
            # An unused member has no worker/session. Reserve its existing route
            # identity without starting a worker so empty history can be adopted.
            route, _ = conversations.store.reserve(scope, run["run_id"],
                run["initial"]["group"]["cwd"], member["binding"]["home"])
            if route.id != member["session_id"]:
                raise DiscussionError("migration_source_changed")
            adopted[member["member_id"]] = conversations.migrate(scope, route.id,
                {"persona_id": target.persona_id, "persona_instance_id": target.id})
        refs = tuple(ParticipantRef.parse(row["participant"]) for row in intent["members"])
        group = run["initial"]["group"]
        spec = RoomSpec(group["name"], refs, DiscussionSettings.parse(group["settings"]))
        # Revalidate every mutable binding after import before switching execution.
        _prepare(service, run, intent, conversations)
        for member in members:
            target = adopted[member["member_id"]]
            service.context.ensure_session({**run, "initial": {"client_scope": owner}},
                {**member, "instance_id": target["persona_instance_id"],
                 "persona_id": target["persona_id"], "session_id": target["session_id"]})
        return {"run": store.commit(service.runs, run, spec, adopted)}
