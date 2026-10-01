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
from pathlib import Path
from typing import Any, Iterator, Mapping

from gateway import hosted_room_discussion as policy
from gateway import hosted_room_driver as driver
from gateway import hosted_rooms as rooms
from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint
from gateway.hosted_room_message_intent import response_from_payload
from tui_gateway.hosted_room_driver import HostedRoomBinding, HostedRoomRuntime

from .attempt_store import AttemptStore
from .definition_store import DefinitionStore
from .native_context import NativeContext
from .session_rpc import NativeSessionRPC
from .run_store import DiscussionError, RunStore
from .room_definition import RoomSpec
from .executions import Executions
from .profile_groups import ProfileGroupSpec, is_group_scope
from .group_admission import admit_group
from .room_state import RoomState
from .room_commands import RoomCommands

__layer__ = "lanes"

logger = logging.getLogger(__name__)


class DiscussionService:
    def __init__(self, context: NativeContext, *, active_poll_interval: float = 0.5, conversations=None) -> None:
        self.context = context
        self.db_path = context.home / "state.db"
        self.definitions = DefinitionStore(self.db_path)
        self.runs = RunStore(self.definitions)
        self.attempts = AttemptStore(self.db_path)
        # Constructors above do no I/O; this is called only after serve ownership.
        with closing(self.runs.connect()), closing(self.attempts.connect()):
            pass
        self.checkpoints = HostedRoomPolicyCheckpoint(self.db_path, max_active_events=256)
        self.executions = Executions(context, self.attempts, self.runs, conversations)
        self.turns = self.executions.instances.turns
        self.state = RoomState(self.db_path, context.install_id, self.runs,
            self.attempts, self.executions, self.checkpoints)
        self._lock = threading.RLock()
        self._started, self._closed, self._draining = False, False, False
        self.runtime = HostedRoomRuntime(
            db_path=self.db_path, rooms=self.bindings, turn_lock=self._turn_lock,
            transport_resolver=self.transport, prepare_room=self.prepare,
            publish_terminal=self.published, active_poll_interval_seconds=active_poll_interval,
            poll_interval_seconds=2.0, turn_timeout_seconds=1830.0)
        self.commands = RoomCommands(self.state, self.runtime, context)

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
        self.executions.close()
        self.context.launcher.close()
        self.runtime.stop(timeout=5.0)

    @property
    def accepting(self) -> bool:
        return self._started and not self._closed and not self._draining

    def begin_drain(self) -> None:
        with self._lock:
            self._draining = True

    @contextmanager
    def idle_drain(self) -> Iterator[None]:
        """Fence admission only if every owner accepts the idle claim."""
        with self._lock:
            if self.runs.owned():
                raise DiscussionError("busy")
            yield
            self._draining = True

    def pending_count(self) -> int:
        # Open rooms may schedule another round between native turns.
        with self._lock:
            return len(self.runs.owned())

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
            self.context.launcher.bind(run["run_id"])
            self.runtime.wakeup()
            return self.runs.get(run["run_id"])

    def begin_room(self, workspace_id: str, spec: RoomSpec, *, key: str,
                   topic: str, actor_id: str) -> dict[str, Any]:
        self.context.workspace(workspace_id)
        with self._lock:
            if not self.accepting:
                raise DiscussionError("runtime_stopping")
            run = self.runs.begin_room(workspace_id, spec, key=key, topic=topic,
                actor_id=actor_id, resolve=self.context.resolve)
            self.context.launcher.bind(run["run_id"])
            self.runtime.wakeup()
            return self.runs.get(run["run_id"])


    def begin_group(self, spec: ProfileGroupSpec, *, key: str, actor_id: str, client: str) -> dict[str, Any]:
        with self._lock:
            if not self.accepting:
                raise DiscussionError("runtime_stopping")
            run = admit_group(self.runs, spec, key=key, actor=actor_id, client=client,
                              install_id=self.context.install_id)
            self.context.launcher.bind(run["run_id"], client_scope=client)
            self.runtime.wakeup()
            return run

    def validate_scope(self, scope: str) -> None:
        if not is_group_scope(scope):
            self.context.workspace(scope)

    def bindings(self) -> list[HostedRoomBinding]:
        with self._lock:
            if self._closed:
                return []
            result = []
            for run in self.runs.owned():
                try:
                    if run["phase"] == "initializing":
                        self.state.initialize(run)
                    elif run["phase"] == "ending":
                        # Repair a crash between disband and claim release.
                        try:
                            ended = self.state.room(run, include_ended=True).get("disbanded_at") is not None
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
        return self.executions.for_run(run).transport(run, member, task)

    def prepare(self, binding: HostedRoomBinding) -> None:
        with self._lock:
            if self._closed:
                return
            run = self.runs.get(binding.room_id)
            if run["phase"] in {"initializing", "ended", "failed"}:
                return
            room = self.state.room(run)
            self.state.publish(run, room)
            self.commands.process(run)
            run = self.runs.get(binding.room_id)
            if run["phase"] != "open":
                return
            room = self.state.room(run)
            if self.state.unresolved(run["run_id"]):
                return
            snapshot = self.checkpoints.snapshot(room_id=run["run_id"], latest_seq=room["latest_seq"])
            active = [m["member_id"] for m in self.runs.members(run["run_id"]) if m["status"] == "active"]
            decision = policy.plan_next_task(room, list(snapshot.events), initial_watermarks=snapshot.watermarks,
                active_member_ids=active, **self.state.policy_args(run))
            if decision.status == "task" and decision.task is not None:
                for task in decision.ready_tasks or (decision.task,):
                    driver.admit_task(self.db_path, task.identity, payload=task.payload, clock=time.time)
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
        self.validate_scope(workspace_id)
        with self._lock:
            # Existing work must still accept answers and exact cancellation.
            continuation = operation in {"answer", "stop", "end", "remove", "abandon"}
            if self._closed or not self._started or (self._draining and not continuation):
                raise DiscussionError("runtime_stopping")
            if operation == "send" and (response := response_from_payload(body)) is not None:
                response.validate_audience((m["member_id"] for m in self.runs.members(run_id) if m["status"] == "active"),
                                           error=lambda _: DiscussionError("member_not_found"))
            admitted = self.runs.request(run_id, workspace_id, key=key, operation=operation,
                expect_revision=expect_revision, body={**body, "actor_id": actor_id})
            run = self.runs.get(run_id)
            if admitted and operation == "send":
                self.context.launcher.admit(run_id, key,
                    client_scope=run["initial"].get("group", {}).get("client"))
            self.commands.process(run)
            self.runtime.wakeup()
            return self.state.view(workspace_id, run_id)

    def view(self, workspace_id: str, run_id: str, *, since_seq: int = 0, limit: int = 100) -> dict[str, Any]:
        return self.state.view(workspace_id, run_id, since_seq=since_seq, limit=limit)

    def respond(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Native request IDs own answer deduplication; never journal secret input here."""
        with self._lock:
            if self._closed or not self._started:
                raise DiscussionError("runtime_stopping")
            run = self.runs.get(body["run_id"], body["workspace_id"])
            if "group" not in run["initial"]:
                raise DiscussionError("unsupported_answer")
            task = self.state.task(run["run_id"], body["task_id"], body["generation"])
            row = self.executions.profiles.row(run["run_id"], task)
            if row is None:
                raise DiscussionError("attempt_not_found")
            self.executions.profiles.turns.answer(row, body)
            self.runtime.wakeup()
            return self.state.view(body["workspace_id"], body["run_id"])

    def active(self, workspace_id: str) -> list[dict[str, Any]]:
        """Bounded scene/status projection; no transcript duplication per polling client."""
        self.validate_scope(workspace_id)
        return [{"run": run, "members": self.runs.members(run["run_id"]),
                 "tasks": self.state.task_rows(run["run_id"])}
                for run in self.runs.owned() if run["workspace_id"] == workspace_id]

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
