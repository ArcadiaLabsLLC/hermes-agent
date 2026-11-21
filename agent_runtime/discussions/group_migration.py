"""Adoption of a paused profile group into its existing native room.

The run's durable intent fences commands across crashes. Each member reuses the
Direct migration receipt; only after every import succeeds do all bindings change
in one transaction. No public event is copied, rewritten or scheduled by adoption.

A profile group runs nothing any more (RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT,
owner 2026-11-21 "yea retire the old path"), so :func:`adopt_legacy_groups` adopts every saved
one at the discussion service's start, with no one asking: each is paused and, when every member's
profile names exactly one agent, moved into the Conversations workspace as an agent room — its room
log, member ids, receipts and each member's transcript kept. A group it cannot adopt is left paused
and whole, named in the log and on the run's ``error``, for ``run.migrate_group`` to adopt with
explicit agents.
"""
from __future__ import annotations

import logging
from pathlib import Path

from agent_runtime.conversation_owner import client_scope, ConversationOwnerError
from agent_runtime.conversations.migration import migration_target
from .definitions import DiscussionSettings, ParticipantRef
from .group_migration_values import member_targets
from .profile_groups import member_scope
from .room_definition import RoomSpec
from .room_owner import room_client_scope
from .run_values import DiscussionError
from . import group_migration_store as store

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: Why a saved group was left for an explicit adoption (``run.migrate_group``).
NO_SINGLE_AGENT = "no_single_agent_for_profile"


def _resolve_migration_members(service, run, intent, conversations):
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
        conversations = service.legacy_routes()
        members, resolved = _resolve_migration_members(service, run, intent, conversations)
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
        _resolve_migration_members(service, run, intent, conversations)
        for member in members:
            target = adopted[member["member_id"]]
            service.context.ensure_session({**run, "initial": {"client_scope": owner}},
                {**member, "instance_id": target["persona_instance_id"],
                 "persona_id": target["persona_id"], "session_id": target["session_id"]})
        return {"run": store.commit(service.runs, run, spec, adopted)}


def _single_agents(service, run, workspace_id):
    """``member_id -> participant`` naming, for each member, the ONE live agent on its profile; ``None``
    when any member's profile has none or several (adoption never guesses between agents)."""
    from agent_runtime.persona_assignments import PersonaInstanceStore

    by_profile: dict[str, list[dict]] = {}
    with service.context.scope():
        scan = PersonaInstanceStore().scan_all()
        for instance in scan.instances:
            try:
                live = service.context.resolve_room(ParticipantRef(service.context.install_id, instance.id),
                                                    workspace_id)
            except DiscussionError:
                continue
            by_profile.setdefault(live["profile"], []).append(live)
    members = service.runs.members(run["run_id"])
    chosen = {m["member_id"]: by_profile.get(m["profile"], []) for m in members}
    if any(len(rows) != 1 for rows in chosen.values()):
        return None
    targets = [{"member_id": mid, "participant": {"install_id": rows[0]["install_id"],
                                                  "instance_id": rows[0]["instance_id"]}}
               for mid, rows in chosen.items()]
    if len({t["participant"]["instance_id"] for t in targets}) != len(targets):
        return None
    return targets


def adopt_legacy_groups(service) -> dict[str, str]:
    """Pause and adopt every saved profile group; ``run_id -> outcome`` (``adopted`` or the reason it waits).

    Called by the service's start, under its lock and before the room worker binds a room. A group
    whose turns were still unsettled at boot is paused now and adopted at a later start, once the room
    worker has settled them (``RetiredGroupTurns`` reads them as failed)."""
    from agent_runtime.workspace_create import conversations_workspace

    outcomes: dict[str, str] = {}
    legacy = [run for run in service.runs.owned() if "group" in run["initial"]
              and (run["initial"].get("group_migration") or {}).get("state") != "complete"]
    if not legacy:
        return outcomes
    with service.context.scope():
        workspace_id = conversations_workspace().id  # Eternia's home for non-spatial conversations
    for run in legacy:
        run_id = run["run_id"]
        try:
            run = store.pause_retired(service.runs, run)
            if run["phase"] != "paused":
                outcomes[run_id] = "phase_" + run["phase"]
                continue
            pending = run["initial"].get("group_migration")
            if pending is not None:  # an adoption a crash cut short finishes on the intent it recorded
                target, members = pending["intent"]["target_workspace_id"], pending["intent"]["members"]
            else:
                target, members = workspace_id, _single_agents(service, run, workspace_id)
            if members is None:
                outcomes[run_id] = NO_SINGLE_AGENT
                service.runs.report_error(run_id, NO_SINGLE_AGENT)
                continue
            group = run["initial"]["group"]
            migrate_group(service, {"client_scope": group["client"], "workspace_id": run["workspace_id"],
                                    "run_id": run_id, "expect_revision": run["revision"],
                                    "target_workspace_id": target, "members": member_targets(members)},
                          run["actor_id"])
            outcomes[run_id] = "adopted"
        except Exception as exc:
            outcomes[run_id] = str(getattr(exc, "reason", None) or type(exc).__name__)
    for run_id, outcome in outcomes.items():
        log = logger.info if outcome == "adopted" else logger.warning
        log("legacy profile group %s: %s", run_id, outcome)
    return outcomes
