"""Native discussion composition: one owned runtime, one existing hosted-room worker.

No widget/process lifetime owns a meeting. Durable command intents compose native
session admission with upstream scheduling. The public room log and the native
turn journal remain the authorities for conversation and execution respectively.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator, Mapping

from gateway import hosted_room_discussion as policy
from gateway import hosted_room_driver as driver
from gateway import hosted_rooms as rooms
from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint
from tui_gateway.hosted_room_driver import HostedRoomBinding, HostedRoomRuntime

from .attempt_store import AttemptStore
from .definition_store import DefinitionStore
from .definitions import ParticipantRef, identifier, revision, plan_seats
from .native import NativeContext, NativeSessionRPC, NativeTurns
from .run_store import DiscussionError, RunStore, digest

__layer__ = "lanes"

logger = logging.getLogger(__name__)
_LIVE_TASKS = frozenset({"queued", "running", "stopping", "indeterminate"})
_TERMINAL = frozenset({"settled", "failed", "cancelled", "deferred"})


class DiscussionService:
    def __init__(self, context: NativeContext, *, active_poll_interval: float = 0.5) -> None:
        self.context = context
        self.db_path = context.home / "state.db"
        self.definitions = DefinitionStore(self.db_path)
        self.runs = RunStore(self.definitions)
        self.attempts = AttemptStore(self.db_path)
        # Constructors above do no I/O; this is called only after serve ownership.
        with closing(self.runs.connect()), closing(self.attempts.connect()):
            pass
        self.checkpoints = HostedRoomPolicyCheckpoint(self.db_path, max_active_events=256)
        self.turns = NativeTurns(context, self.attempts)
        self._lock = threading.RLock()
        self._started, self._closed = False, False
        self._processing: set[str] = set()
        self.runtime = HostedRoomRuntime(
            db_path=self.db_path, rooms=self.bindings, turn_lock=self._turn_lock,
            transport_resolver=self.transport, prepare_room=self.prepare,
            publish_terminal=self.published, active_poll_interval_seconds=active_poll_interval,
            poll_interval_seconds=2.0, turn_timeout_seconds=1830.0)

    @staticmethod
    @contextmanager
    def _turn_lock(_profile: str) -> Iterator[None]:
        # Native admission acquires the exact session lease and profile runner
        # lock. A second profile lock here would serialize unrelated room input
        # waits and can deadlock recursive native delegation.
        yield

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise DiscussionError("runtime_stopping")
            self.runtime.start()
            self._started = True

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self.turns.close()
        self.runtime.stop(timeout=5.0)

    @property
    def accepting(self) -> bool:
        return self._started and not self._closed

    def begin(self, workspace_id: str, table_id: str, *, expect_revision: int,
              key: str, topic: str, actor_id: str) -> dict[str, Any]:
        if not self.accepting:
            raise DiscussionError("runtime_stopping")
        self.context.workspace(workspace_id)
        with self._lock:
            if not self.accepting:
                raise DiscussionError("runtime_stopping")
            run = self.runs.begin(workspace_id, table_id, expect_revision=expect_revision,
                key=key, topic=topic, actor_id=actor_id, resolve=self.context.resolve)
            # Durable admission ACK; initialization runs on the existing worker.
            self.runtime.wakeup()
            return self.runs.get(run["run_id"])

    def _room(self, run: Mapping[str, Any], *, include_ended: bool = False) -> dict[str, Any]:
        room = rooms.room_state(self.db_path, room_id=run["run_id"], include_disbanded=include_ended)
        if room["authority_gateway_id"] != self.context.install_id or room["authority_epoch"] != 1:
            raise DiscussionError("authority_changed")
        # Historical catalog is monotonic; active membership is independent.
        # Stored hosted birth roster remains immutable (idempotent Start replay).
        return {**room, "members": self._roster(self.runs.members(run["run_id"]))}

    @staticmethod
    def _roster(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: m[k] for k in ("member_id", "profile", "handle", "display_name")} for m in members]

    def _limits(self, run: Mapping[str, Any]) -> policy.DiscussionLimits:
        config = run["initial"]["table"]["spec"]["configuration"]
        settings = config["settings"]
        guidance = ""
        moderator = settings["moderator"]
        if moderator is not None:
            members = self.runs.members(run["run_id"])
            member = next((m for m in members if (m["install_id"], m["instance_id"]) ==
                           (moderator["install_id"], moderator["instance_id"])), None)
            if member is not None:
                guidance = f"- @{member['handle']} coordinates this discussion and should synthesize conclusions; this grants no extra tool permissions."
        return policy.DiscussionLimits(max_members=128, max_rounds=settings["rounds"],
            max_messages=run["initial"]["seat_plan"]["capacity"] * settings["rounds"],
            shared_profiles=True, prompt_bytes=12000, guidance=guidance)

    def _policy_args(self, run: Mapping[str, Any]) -> dict[str, Any]:
        return {"local_profiles": {m["profile"] for m in self.runs.members(run["run_id"])}, "limits": self._limits(run)}

    def _initialize(self, run: Mapping[str, Any]) -> None:
        members = self.runs.members(run["run_id"])
        for member in members:
            live = self.context.resolve(ParticipantRef(member["install_id"], member["instance_id"]), run["workspace_id"])
            if any(live[k] != member[k] for k in ("persona_id", "profile")):
                raise DiscussionError("profile_binding_changed")
            self.context.ensure_session(run, member)
        rooms.create_room(self.db_path, room_id=run["run_id"],
            name=run["initial"]["table"]["spec"]["name"][:200], members=self._roster(members),
            authority_gateway_id=self.context.install_id)
        # NOT pinned here. A retention pin only matters once the room is disbanded
        # -- a live room is not a prune candidate at all -- and a pin taken at
        # Start is never released for a run that is abandoned, crashes, or is
        # simply left open, so the pin table grew by one per run FOREVER and a
        # full table then refused every later Start. The pin is taken in
        # _finalize_room, immediately before disband, which is the one moment it
        # protects anything. See docs/agent-runtime-harness/planned/
        # discussion-tables-local-handoff.md.
        self._append_user(run, "start", run["topic"], actor_id=run["actor_id"])
        self.runs.activate(run["run_id"])

    def bindings(self) -> list[HostedRoomBinding]:
        with self._lock:
            if self._closed:
                return []
            result = []
            for run in self.runs.owned():
                try:
                    if run["phase"] == "initializing":
                        self._initialize(run)
                    elif run["phase"] == "ending":
                        # Repair a crash between disband and claim release.
                        try:
                            ended = self._room(run, include_ended=True).get("disbanded_at") is not None
                        except rooms.RoomNotFoundError:
                            ended = not self.attempts.rows(run["run_id"])
                        if ended:
                            self.runs.end(run["run_id"])
                            continue
                    result.append(HostedRoomBinding(run["run_id"], self.context.install_id, 1))
                except Exception as exc:
                    reason = getattr(exc, "reason", "initialization_failed")
                    self.runs.report_error(run["run_id"], reason)
                    logger.warning("Discussion initialization held: %s (%s)", run["run_id"], reason)
            return result

    def transport(self, binding: HostedRoomBinding, task: Mapping[str, Any]) -> NativeSessionRPC:
        run = self.runs.get(binding.room_id)
        member = next((m for m in self.runs.members(binding.room_id)
                       if m["member_id"] == task["payload"]["target_member_id"]), None)
        if member is None:
            raise DiscussionError("member_not_found")
        return NativeSessionRPC(self.turns, run, member, task)

    def _publish(self, run: Mapping[str, Any], room: Mapping[str, Any]) -> None:
        rid = run["run_id"]
        self.checkpoints.snapshot(room_id=rid, latest_seq=room["latest_seq"])
        for task in driver.list_tasks(self.db_path, room_id=rid):
            status, generation = task["status"], task["execution_generation"]
            if status not in _TERMINAL or self.checkpoints.publication_exists(
                    room_id=rid, task_id=task["identity"].task_id, status=status, execution_generation=generation):
                continue
            events = self.checkpoints.events_for_task(room_id=rid, source_event_seq=task["payload"]["source_event_seq"])
            plan = policy.reconstruct_task_plan(room, events, task, **self._policy_args(run))
            publication = policy.plan_publication(room, events, plan, status=status,
                result=task.get("result"), execution_generation=generation if status == "deferred" else None,
                **self._policy_args(run))
            for event in publication.events:
                rooms.append_event(self.db_path, **event.append_kwargs(rid))
        self.checkpoints.snapshot(room_id=rid, latest_seq=self._room(run)["latest_seq"])

    def _unresolved(self, run_id: str, member_id: str | None = None) -> bool:
        # Only CURRENT task generations count. Earlier generations stay as audit
        # rows after an explicitly approved retry; they cannot lock a new run.
        for task in driver.list_tasks(self.db_path, room_id=run_id):
            if member_id is not None and task["payload"]["target_member_id"] != member_id:
                continue
            if task["status"] in _LIVE_TASKS:
                return True
            row = self.attempts.get(run_id, task["identity"].task_id, task["execution_generation"])
            if row is not None and (self.turns.is_live(row) or self.turns.recover(row)["stage"] != "terminal"):
                return True
        return False

    def prepare(self, binding: HostedRoomBinding) -> None:
        with self._lock:
            if self._closed:
                return
            run = self.runs.get(binding.room_id)
            if run["phase"] in {"initializing", "ended", "failed"}:
                return
            room = self._room(run)
            self._publish(run, room)
            self._commands(run)
            run = self.runs.get(binding.room_id)
            if run["phase"] != "open":
                return
            room = self._room(run)
            if self._unresolved(run["run_id"]):
                return
            snapshot = self.checkpoints.snapshot(room_id=run["run_id"], latest_seq=room["latest_seq"])
            active = [m["member_id"] for m in self.runs.members(run["run_id"]) if m["status"] == "active"]
            decision = policy.plan_next_task(room, list(snapshot.events), initial_watermarks=snapshot.watermarks,
                active_member_ids=active, **self._policy_args(run))
            if decision.status == "task" and decision.task is not None:
                driver.admit_task(self.db_path, decision.task.identity, payload=decision.task.payload, clock=time.time)
            elif decision.status in {"settled", "bounded"}:
                rooms.append_event(self.db_path, room_id=run["run_id"],
                    event_id=f"dactivity:{decision.discussion_event_id}:{decision.reason}", kind="room.activity",
                    actor={"kind": "gateway", "id": self.context.install_id},
                    payload={"status": decision.status, "reason_code": decision.reason,
                        "thread_id": decision.thread_id, "discussion_event_id": decision.discussion_event_id},
                    authority_gateway_id=self.context.install_id, authority_epoch=1)
            self.checkpoints.compact_completed(room_id=run["run_id"])
            driver.prune_published_terminal_tasks(self.db_path, room_id=run["run_id"], clock=time.time)

    def published(self, binding: HostedRoomBinding, _task: Mapping[str, Any]) -> None:
        self.prepare(binding)
        self.runtime.wakeup()

    def command(self, workspace_id: str, run_id: str, operation: str, *, key: str,
                expect_revision: int, body: Mapping[str, Any], actor_id: str) -> dict[str, Any]:
        if not self.accepting:
            raise DiscussionError("runtime_stopping")
        self.context.workspace(workspace_id)
        with self._lock:
            if not self.accepting:
                raise DiscussionError("runtime_stopping")
            self.runs.request(run_id, workspace_id, key=key, operation=operation,
                expect_revision=expect_revision, body={**body, "actor_id": actor_id})
            self._commands(self.runs.get(run_id))
            self.runtime.wakeup()
            return self.view(workspace_id, run_id)

    def _task(self, run_id: str, task_id: str, generation: int) -> dict[str, Any]:
        task = next((t for t in driver.list_tasks(self.db_path, room_id=run_id) if t["identity"].task_id == task_id), None)
        if task is None:
            raise DiscussionError("task_not_found")
        if task["execution_generation"] != generation:
            raise DiscussionError("stale_attempt")
        return task

    def _append_user(self, run: Mapping[str, Any], key: str, message: str, *, actor_id: str) -> None:
        rooms.append_event(self.db_path, room_id=run["run_id"], event_id="user:" + digest({"key": key})[:40],
            kind="message.user", actor={"kind": "user", "id": actor_id},
            payload={"text": message, "thread_id": "discussion"},
            authority_gateway_id=self.context.install_id, authority_epoch=1)

    def _cancel(self, run: Mapping[str, Any], key: str, member_id: str | None = None) -> None:
        for task in driver.list_tasks(self.db_path, room_id=run["run_id"]):
            if task["status"] in {"settled", "failed", "cancelled"}:
                continue
            if member_id is not None and task["payload"]["target_member_id"] != member_id:
                continue
            self.runtime.cancel(task["identity"], cancel_id=task.get("cancel_id") or key)

    def _retain(self, run_id: str) -> str | None:
        """Pin the meeting transcript; retention is host storage policy, not authority.

        End is not Delete history, but a host that cannot retain one more
        transcript must still be able to END the meeting: the transcript falls
        back to ordinary deleted-chat retention and the typed refusal is surfaced
        on the run, rather than stranding it in ``ending`` holding its table and
        instance claims. Returns that reason, or None when the pin was taken.
        """
        try:
            rooms.pin_room_history(self.db_path, room_id=run_id,
                expected_gateway_id=self.context.install_id, expected_epoch=1)
            return None
        except rooms.HostedRoomError as exc:
            reason = getattr(exc, "reason", None) or "history_retention_unavailable"
            logger.warning("Discussion transcript not retained: %s (%s)", run_id, reason)
            return reason

    def _release(self, run_id: str) -> None:
        """Drop a retention claim that no longer has a disbanded room behind it."""
        try:
            rooms.unpin_room_history(self.db_path, room_id=run_id,
                expected_gateway_id=self.context.install_id, expected_epoch=1)
        except rooms.HostedRoomError:
            logger.warning("Discussion retention release deferred: %s", run_id)

    def _finalize_room(self, run: Mapping[str, Any]) -> str | None:
        """Publish, retain and disband, without being able to strand the run.

        Returns a typed retention refusal to surface, or None.
        """
        rid, refusal = run["run_id"], None
        try:
            room = self._room(run, include_ended=True)
            if room.get("disbanded_at") is None:
                self._publish(run, room)
                refusal = self._retain(rid)
                try:
                    rooms.disband_room(self.db_path, room_id=rid,
                        expected_gateway_id=self.context.install_id, expected_epoch=1)
                except Exception:
                    if refusal is None:
                        self._release(rid)  # Never leave a pin on a room still live.
                    raise
        except rooms.RoomNotFoundError:
            if self.attempts.rows(rid):
                raise
        return refusal

    def _commands(self, initial: Mapping[str, Any]) -> None:
        rid = initial["run_id"]
        if rid in self._processing:
            return  # A cancellation's terminal callback can re-enter prepare.
        self._processing.add(rid)
        try:
            self._process_commands(initial)
        finally:
            self._processing.discard(rid)

    def _process_commands(self, initial: Mapping[str, Any]) -> None:
        rid = initial["run_id"]
        # Stop/End precede normal queued sends; native answers/recovery stay usable
        # while work is stopping. All operations are idempotent through this row.
        pending = self.runs.pending(rid)
        pending.sort(key=lambda c: (0 if c["operation"] in {"stop", "end", "abandon"} else 1, c["created_at"]))
        for cmd in pending:
            run, body, key, op = self.runs.get(rid), cmd["body"], cmd["command_key"], cmd["operation"]
            try:
                if op in {"stop", "end"}:
                    try:
                        rooms.request_room_stop(self.db_path, room_id=rid, cancel_id=key,
                            expected_gateway_id=self.context.install_id, expected_epoch=1)
                        self._cancel(run, key)
                    except rooms.RoomNotFoundError:
                        if self.attempts.rows(rid):
                            raise
                    if self._unresolved(rid):
                        continue
                    refusal = self._finalize_room(run) if op == "end" else None
                    if op == "end":
                        self.runs.end(rid)
                    self.runs.finish_command(rid, key, phase="paused" if op == "stop" else None)
                    if refusal is not None:
                        # finish_command clears the run error, and a retention
                        # refusal is not this command's outcome: End succeeded.
                        self.runs.report_error(rid, refusal)
                elif op == "send":
                    if self._unresolved(rid):
                        continue
                    self._append_user(run, key, body["message"], actor_id=body["actor_id"])
                    self.runs.finish_command(rid, key, phase="open")
                elif op == "invite":
                    if not run["initial"]["table"]["spec"]["configuration"]["settings"]["allow_invitations"]:
                        raise DiscussionError("invitations_disabled")
                    live = self.context.resolve(ParticipantRef.parse(body["participant"]), run["workspace_id"])
                    member = self.runs.join(rid, live)
                    self.context.ensure_session(run, member)
                    self.runs.set_member_status(rid, member["member_id"], "active")
                    self.runs.finish_command(rid, key)
                elif op == "remove":
                    mid = body["member_id"]
                    member = next((m for m in self.runs.members(rid) if m["member_id"] == mid), None)
                    if member is None:
                        raise DiscussionError("member_not_found")
                    if member["status"] != "removed":
                        self.runs.set_member_status(rid, mid, "removing")
                        self._cancel(run, key, mid)
                        if self._unresolved(rid, mid):
                            continue
                        self.runs.set_member_status(rid, mid, "removed")
                    self.runs.finish_command(rid, key)
                else:
                    task = self._task(rid, body["task_id"], body["generation"])
                    row = self.attempts.get(rid, body["task_id"], body["generation"])
                    if row is None:
                        raise DiscussionError("attempt_not_found")
                    if op == "answer":
                        row = self.attempts.answer(rid, body["task_id"], body["generation"],
                            expected_native_id=body["native_id"], key=key, answer=body["answer"])
                        member = next(m for m in self.runs.members(rid) if m["member_id"] == row["member_id"])
                        self.turns.launch(run, member, row, lambda _receipt: self.runtime.request_reconciliation(task["identity"]))
                    elif op == "retry":
                        if not self.turns.execution_absent(row):
                            raise DiscussionError("execution_still_live")
                        self.runtime.retry_indeterminate(task["identity"])
                    elif op == "abandon":
                        if body["native_id"] != row["native_id"]:
                            raise DiscussionError("stale_attempt")
                        self.turns.abandon(row)
                        self.runtime.request_reconciliation(task["identity"])
                    self.runs.finish_command(rid, key)
            except (DiscussionError, ValueError) as exc:
                self.runs.finish_command(rid, key, error=getattr(exc, "reason", "operation_refused"))
            except Exception:
                # May have committed; keep the SAME command pending for recovery.
                self.runs.report_error(rid, "operation_outcome_unknown")
                logger.exception("Discussion command awaits reconciliation: %s %s", rid, op)

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
        tasks = self._task_rows(run_id)
        return {"run": run, "members": self.runs.members(run_id), "tasks": tasks,
                "log": page, "commands": self.runs.commands(run_id), "history_error": room_error}

    def active(self, workspace_id: str) -> list[dict[str, Any]]:
        """Bounded scene/status projection; no transcript duplication per polling client."""
        self.context.workspace(workspace_id)
        return [{"run": run, "members": self.runs.members(run["run_id"]),
                 "tasks": self._task_rows(run["run_id"])}
                for run in self.runs.owned() if run["workspace_id"] == workspace_id]

    def _task_rows(self, run_id: str) -> list[dict[str, Any]]:
        tasks = []
        for task in driver.list_tasks(self.db_path, room_id=run_id):
            row = self.attempts.get(run_id, task["identity"].task_id, task["execution_generation"])
            if row is not None:
                row = self.turns.recover(row)
            tasks.append({"task_id": task["identity"].task_id, "member_id": task["payload"]["target_member_id"],
                "generation": task["execution_generation"], "status": task["status"],
                "attempt_stage": row["stage"] if row else None, "native_id": row["native_id"] if row else None,
                "question": row["question"] if row else None,
                "error": (row["receipt"] or {}).get("error") if row else None})
        return tasks


_owner_lock = threading.RLock()
_owner: DiscussionService | None = None


def bind(root: Path, home: Path, install_id: str) -> DiscussionService:
    """Called only while holding the existing serve socket-owner lock."""
    global _owner
    with _owner_lock:
        if _owner is not None:
            if (_owner.context.root, _owner.context.home) != (root.resolve(), home.resolve()):
                raise DiscussionError("runtime_owner_conflict")
            return _owner
        _owner = DiscussionService(NativeContext(root, home, install_id))
        return _owner


def get_service() -> DiscussionService:
    with _owner_lock:
        if _owner is None:
            raise DiscussionError("discussion_service_unavailable")
        return _owner


def shutdown(*, root: Path) -> None:
    global _owner
    with _owner_lock:
        owner = _owner
        if owner is None or owner.context.root != root.resolve():
            return
        _owner = None
    owner.close()
