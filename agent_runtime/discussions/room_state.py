"""Room policy and read projection over the existing hosted-room journal."""
from __future__ import annotations

import logging
from typing import Any, Mapping

from gateway import hosted_room_discussion as policy
from gateway import hosted_room_driver as driver
from gateway import hosted_rooms as rooms
from .definitions import identifier, revision
from .room_definition import execution_spec
from .run_values import DiscussionError, digest

__layer__ = "lanes"

logger = logging.getLogger(__name__)
_LIVE_TASKS = frozenset({"queued", "running", "stopping", "indeterminate"})
_TERMINAL = frozenset({"settled", "failed", "cancelled", "deferred"})


class RoomState:
    def __init__(self, db_path, install_id, runs, attempts, executions, checkpoints):
        self.db_path, self.install_id = db_path, install_id
        self.runs, self.attempts, self.executions = runs, attempts, executions
        self.checkpoints = checkpoints

    @staticmethod
    def roster(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: m[k] for k in ("member_id", "profile", "handle", "display_name")} for m in members]

    def room(self, run: Mapping[str, Any], *, include_ended: bool = False) -> dict[str, Any]:
        room = rooms.room_state(self.db_path, room_id=run["run_id"], include_disbanded=include_ended)
        if room["authority_gateway_id"] != self.install_id or room["authority_epoch"] != 1:
            raise DiscussionError("authority_changed")
        # Historical catalog is monotonic; active membership is independent.
        # Stored hosted birth roster remains immutable (idempotent Start replay).
        return {**room, "members": self.roster(self.runs.members(run["run_id"]))}

    def limits(self, run: Mapping[str, Any]) -> policy.DiscussionLimits:
        spec = execution_spec(run)
        settings = spec.settings
        guidance = ""
        conclusion_member = None
        moderator = settings["moderator"]
        if moderator is not None:
            members = self.runs.members(run["run_id"])
            member = next((m for m in members if (m["install_id"], m["instance_id"]) ==
                           (moderator["install_id"], moderator["instance_id"])), None)
            if member is not None:
                guidance = f"- @{member['handle']} coordinates this discussion and should synthesize conclusions; this grants no extra tool permissions."
                if settings.get("synthesize", False):
                    conclusion_member = member["member_id"]
        return policy.DiscussionLimits(max_members=128, max_rounds=settings["rounds"],
            max_messages=spec.capacity * settings["rounds"],
            shared_profiles=True, prompt_bytes=12000, guidance=guidance,
            conclusion_member_id=conclusion_member)

    def policy_args(self, run: Mapping[str, Any]) -> dict[str, Any]:
        return {"local_profiles": {m["profile"] for m in self.runs.members(run["run_id"])}, "limits": self.limits(run)}

    def initialize(self, run: Mapping[str, Any]) -> None:
        members = self.runs.members(run["run_id"])
        self.executions.for_run(run).initialize(run, members)
        rooms.create_room(self.db_path, room_id=run["run_id"],
            name=execution_spec(run).name[:200], members=self.roster(members),
            authority_gateway_id=self.install_id)
        # Pin only on End; live rooms are not retention candidates.
        if run["topic"]:
            self.append_user(run, "start", run["topic"], actor_id=run["actor_id"])
        self.runs.activate(run["run_id"])

    def publish(self, run: Mapping[str, Any], room: Mapping[str, Any]) -> None:
        rid = run["run_id"]
        self.checkpoints.snapshot(room_id=rid, latest_seq=room["latest_seq"])
        for task in driver.list_tasks(self.db_path, room_id=rid):
            status, generation = task["status"], task["execution_generation"]
            if status not in _TERMINAL or self.checkpoints.publication_exists(
                    room_id=rid, task_id=task["identity"].task_id, status=status, execution_generation=generation):
                continue
            events, plan = self.task_plan(run, room, task)
            publication = policy.plan_publication(room, events, plan, status=status,
                result=task.get("result"), execution_generation=generation if status == "deferred" else None,
                **self.policy_args(run))
            for event in publication.events:
                rooms.append_event(self.db_path, **event.append_kwargs(rid))
        self.checkpoints.snapshot(room_id=rid, latest_seq=self.room(run)["latest_seq"])

    def unresolved(self, run_id: str, member_id: str | None = None) -> bool:
        # Only CURRENT task generations count. Earlier generations stay as audit
        # rows after an explicitly approved retry; they cannot lock a new run.
        execution = self.executions.for_run(self.runs.get(run_id))
        for task in driver.list_tasks(self.db_path, room_id=run_id):
            if member_id is not None and task["payload"]["target_member_id"] != member_id:
                continue
            if task["status"] in _LIVE_TASKS:
                return True
            if execution.unresolved(execution.row(run_id, task)):
                return True
        return False

    def append_user(self, run: Mapping[str, Any], key: str, message: str, *, actor_id: str,
                     response: Mapping[str, Any] | None = None) -> None:
        rooms.append_event(self.db_path, room_id=run["run_id"], event_id="user:" + digest({"key": key})[:40],
            kind="message.user", actor={"kind": "user", "id": actor_id},
            payload={"text": message, "thread_id": "discussion",
                     **({"response": response} if response is not None else {})},
            authority_gateway_id=self.install_id, authority_epoch=1)

    def retain(self, run_id: str) -> str | None:
        """Retain Ended history; a full retention budget must not prevent End."""
        try:
            rooms.pin_room_history(self.db_path, room_id=run_id,
                expected_gateway_id=self.install_id, expected_epoch=1)
            return None
        except rooms.HostedRoomError as exc:
            reason = getattr(exc, "reason", None) or "history_retention_unavailable"
            logger.warning("Discussion transcript not retained: %s (%s)", run_id, reason)
            return reason

    def release(self, run_id: str) -> None:
        """Drop a retention claim that no longer has a disbanded room behind it."""
        try:
            rooms.unpin_room_history(self.db_path, room_id=run_id,
                expected_gateway_id=self.install_id, expected_epoch=1)
        except rooms.HostedRoomError:
            logger.warning("Discussion retention release deferred: %s", run_id)

    def finalize_room(self, run: Mapping[str, Any]) -> str | None:
        """Publish and disband; return any retention refusal."""
        rid, refusal = run["run_id"], None
        try:
            room = self.room(run, include_ended=True)
            if room.get("disbanded_at") is None:
                self.publish(run, room)
                refusal = self.retain(rid)
                try:
                    rooms.disband_room(self.db_path, room_id=rid,
                        expected_gateway_id=self.install_id, expected_epoch=1)
                except Exception:
                    if refusal is None:
                        self.release(rid)  # Never leave a pin on a room still live.
                    raise
        except rooms.RoomNotFoundError:
            if self.attempts.rows(rid):
                raise
        return refusal

    def task(self, run_id: str, task_id: str, generation: int) -> dict[str, Any]:
        task = next((t for t in driver.list_tasks(self.db_path, room_id=run_id) if t["identity"].task_id == task_id), None)
        if task is None:
            raise DiscussionError("task_not_found")
        if task["execution_generation"] != generation:
            raise DiscussionError("stale_attempt")
        return task

    def view(self, workspace_id: str, run_id: str, *, since_seq: int = 0, limit: int = 100) -> dict[str, Any]:
        identifier(workspace_id, "workspace_id")
        revision(since_seq, "since_seq")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise DiscussionError("invalid_limit")
        run = self.runs.get(run_id, workspace_id)
        try:
            page = rooms.read_events(self.db_path, room_id=run_id, since_seq=since_seq, limit=limit, include_disbanded=True)
            room_error = None
        except rooms.RoomNotFoundError:
            page = {"events": [], "cursor": 0, "latest_seq": 0, "has_more": False}
            room_error = None if run["phase"] == "initializing" else "room_history_unavailable"
        tasks = self.task_rows(run_id)
        return {"run": run, "members": self.runs.members(run_id), "tasks": tasks,
                "log": page, "commands": self.runs.commands(run_id), "history_error": room_error}

    def task_rows(self, run_id: str) -> list[dict[str, Any]]:
        tasks = []
        run = self.runs.get(run_id)
        limits = self.limits(run)
        execution = self.executions.for_run(run)
        for task in driver.list_tasks(self.db_path, room_id=run_id):
            row = execution.row(run_id, task)
            tasks.append({"task_id": task["identity"].task_id, "member_id": task["payload"]["target_member_id"],
                "round_index": policy.task_round_index(task["identity"], limits=limits),
                "source_event_seq": task["payload"]["source_event_seq"],
                "generation": task["execution_generation"], "status": task["status"],
                "attempt_stage": row["stage"] if row else None, "native_id": row["native_id"] if row else None,
                "question": row["question"] if row else None,
                "error": (row["receipt"] or {}).get("error") if row else None})
        return tasks

    def task_plan(self, run, room, task):
        events = self.checkpoints.events_for_task(
            room_id=run["run_id"], source_event_seq=task["payload"]["source_event_seq"])
        return events, policy.reconstruct_task_plan(room, events, task, **self.policy_args(run))
