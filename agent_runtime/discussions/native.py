"""Instance-bound adapter over the native chat lane and exact interrupt scopes."""
from __future__ import annotations

import contextvars
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator, Mapping

from agent.interrupt_scope import InterruptScope, bind_interrupt_scope
from agent_runtime.auxiliary_chat import auxiliary_chat
from agent_runtime.resolution import resolve_runtime, runtime_resolution_scope
from hermes_constants import (set_hermes_home_override, reset_hermes_home_override)
from agent_runtime.profile_home import (
    record_hermes_head_home_if_unset,
    reset_hermes_head_home,
    get_hermes_head_home,
)

from .attempt_store import AttemptStore
from .definitions import ParticipantRef
from .run_store import DiscussionError
from agent_runtime.errors import NotFound

log = logging.getLogger(__name__)


class NativeContext:
    """Captured by the socket-owning serve, never from client parameters."""
    def __init__(self, root: Path, home: Path, install_id: str,
                 *, invoke: Callable[[Any], int] | None = None) -> None:
        self.root, self.home, self.install_id = root.resolve(), home.resolve(), install_id
        self.resolution = resolve_runtime({"HERMES_AGENT_RUNTIME_ROOT": str(self.root), "HERMES_HOME": str(self.home)})
        self.invoke = invoke or _invoke_native

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

    def resolve(self, ref: ParticipantRef, workspace_id: str) -> dict[str, Any]:
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
            if effective_workspace_id(instance, active_workspace_id=workspace_id) != workspace_id:
                raise DiscussionError("foreign_workspace", instance_id=ref.instance_id)
            personas = {p.id: p for p in ensure_persisted_personas(load_agent_runtime_config())}
            persona = personas.get(instance.persona_id)
            if persona is None or not is_runtime_persona(persona):
                raise DiscussionError("persona_not_found", instance_id=ref.instance_id)
            binding = resolve_persona_profile(persona)
            if binding.readiness != "ready":
                raise DiscussionError("profile_unavailable", instance_id=ref.instance_id)
            return {**ref.to_dict(), "persona_id": instance.persona_id,
                    "profile": binding.hermes_profile or active_profile_name(),
                    "display_name": instance.display_name}

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
    from hermes_cli.harness_parts.persona import chat_turn_message
    return chat_turn_message._cmd_mission_chat_message(args)


class NativeTurns:
    """Process-local workers; accepted work and recovery coordinates live in SQLite."""
    def __init__(self, context: NativeContext, attempts: AttemptStore, *, max_seconds: float = 240) -> None:
        self.context, self.attempts, self.max_seconds = context, attempts, max_seconds
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="native-discussion")
        self._lock = threading.RLock()
        self._live: dict[tuple[str, str, int], InterruptScope] = {}
        self._closed = False
        from gateway.status import get_process_start_time
        self.pid = os.getpid()
        self.started = get_process_start_time(self.pid)
        if self.started is None:
            raise DiscussionError("process_identity_unavailable")

    def _key(self, row: Mapping[str, Any]) -> tuple[str, str, int]:
        return row["run_id"], row["task_id"], row["generation"]

    def is_live(self, row: Mapping[str, Any]) -> bool:
        with self._lock:
            return self._key(row) in self._live

    def launch(self, run: Mapping[str, Any], member: Mapping[str, Any], row: Mapping[str, Any], on_terminal=None) -> None:
        key = self._key(row)
        with self._lock:
            if key in self._live:
                return
            if self._closed:
                raise DiscussionError("runtime_stopping")
            scope = InterruptScope()
            self._live[key] = scope
            try:
                # A clean Context prevents a caller's alternate profile from becoming
                # this background worker's implicit head. The owner is explicit below.
                self._pool.submit(contextvars.Context().run, self._execute, run, member, row, scope, on_terminal)
            except BaseException:
                self._live.pop(key, None)
                raise

    def recover(self, row: Mapping[str, Any]) -> dict[str, Any]:
        current = self.attempts.get(*self._key(row)) or dict(row)
        if current["stage"] in {"terminal", "waiting_input"}:
            return current
        record = self.context.journal(current["session_id"], current["native_id"])
        if record is not None and record.get("native_committed") is True:
            meta = record.get("auxiliary_result")
            if not isinstance(meta, dict) or "clarify" not in meta:
                return current  # Cannot prove whether a committed turn asked a question.
            question = meta["clarify"]
            if question:
                self.attempts.update(current, stage="waiting_input", question=question)
            else:
                receipt = {"status": "settled", "text": record.get("stored_reply", ""),
                           "settlement_id": current["native_id"], "message_id": current["native_id"]}
                self.attempts.update(current, stage="terminal", receipt=receipt)
        elif record is not None and record.get("state") in {"interrupted", "failed", "budget_exhausted"}:
            self.attempts.update(current, stage="terminal", receipt={
                "status": "cancelled" if record["state"] == "interrupted" else "failed",
                "error": "Native turn " + record["state"], "text": "", "message_id": current["native_id"]})
        return self.attempts.get(*self._key(current)) or current

    def _execute(self, run, member, row, scope, callback) -> None:
        try:
            if not self.attempts.claim(row, pid=self.pid, started=self.started):
                return  # Another owner already accepted this exact native identity.
            payloads: list[dict[str, Any]] = []
            with self.context.scope(), auxiliary_chat(member["instance_id"], member["session_id"]), bind_interrupt_scope(scope):
                live = self.context.resolve(ParticipantRef(member["install_id"], member["instance_id"]), run["workspace_id"])
                if any(live[k] != member[k] for k in ("persona_id", "profile")):
                    raise DiscussionError("profile_binding_changed")
                if scope.reason is not None:
                    self.attempts.update(row, stage="terminal", receipt={"status": "cancelled", "text": ""})
                    return
                args = SimpleNamespace(
                    persona_id=member["persona_id"], persona_instance_id=member["instance_id"],
                    session_id=member["session_id"], clarify_token=None, new_session=False,
                    task_id=None, goal_id=None, title=None, message=row["prompt"],
                    provider=None, model=None, use_agent_default=False, surface_prompt="", intent_hint="chat",
                    requested_by="discussion:" + run["run_id"], client_message_id=row["native_id"],
                    stream=False, max_seconds=self.max_seconds, json=True, requested_by_session=None,
                    workspace_id=run["workspace_id"], relay_chain=[], relay_deadline_epoch=None,
                    payload_sink=payloads.append)
                code = self.context.invoke(args)
            current = self.recover(row)
            if current["stage"] not in {"terminal", "waiting_input"}:
                payload = payloads[-1] if payloads else {}
                uncertain = payload.get("turn_resolution_required") or payload.get("execution_state") == "outcome_unknown"
                if code and not uncertain:
                    self.attempts.update(row, stage="terminal", receipt={"status": "failed", "text": "",
                        "error": str(payload.get("error_kind") or "native_turn_refused"), "message_id": row["native_id"]})
                else:
                    self.attempts.update(row, stage="uncertain")
        except DiscussionError as exc:
            self.attempts.update(row, stage="terminal", receipt={"status": "failed", "text": "", "error": exc.reason, "message_id": row["native_id"]})
        except Exception:
            # The call may have committed before raising. Never turn uncertainty
            # into a success or a fresh automatic execution.
            log.exception("Native discussion attempt failed before observation")
            current = self.recover(row)
            if current["stage"] not in {"terminal", "waiting_input"}:
                self.attempts.update(row, stage="uncertain")
        finally:
            with self._lock:
                self._live.pop(self._key(row), None)
            current = self.attempts.get(*self._key(row))
            if callback is not None and current is not None and current["stage"] == "terminal":
                callback(current["receipt"])

    def execution_absent(self, row: Mapping[str, Any]) -> bool:
        """Positive process-exit proof. Unreadable owner identity is never idle."""
        if self.is_live(row):
            return False
        current = self.attempts.get(*self._key(row)) or row
        if current["stage"] in {"terminal", "pending", "waiting_input"}:
            return True
        if (current.get("owner_pid"), current.get("owner_started")) == (self.pid, self.started):
            # This owner's future left its finally; launch registers before claiming.
            return True
        pid, stamp = current.get("owner_pid"), current.get("owner_started")
        if type(pid) is not int or type(stamp) is not int:
            return False
        from gateway.status import get_process_start_time
        observed = get_process_start_time(pid)
        if observed is not None:
            return observed != stamp  # PID reused, not the old turn.
        try:
            import psutil
            psutil.Process(pid).status()
        except psutil.NoSuchProcess:
            return True
        except (psutil.Error, OSError):
            return False
        return False

    def abandon(self, row: Mapping[str, Any]) -> None:
        """Operator-approved retirement of an unknown outcome, never a success."""
        if not self.execution_absent(row):
            raise DiscussionError("execution_still_live")
        self.attempts.update(row, stage="terminal", receipt={"status": "failed", "text": "",
            "error": "indeterminate_outcome_explicitly_abandoned", "message_id": row["native_id"]})

    def interrupt(self, row: Mapping[str, Any]) -> bool:
        with self._lock:
            scope = self._live.get(self._key(row))
        if scope is not None:
            scope.cancel("Discussion turn stopped by operator")
            return False  # Request is not acknowledgement. Wait for actual exit.
        current = self.recover(row)
        if current["stage"] == "waiting_input" or current["stage"] == "pending":
            self.attempts.update(current, stage="terminal", receipt={"status": "cancelled", "text": ""})
            return True
        return current["stage"] == "terminal"

    def close(self) -> None:
        with self._lock:
            self._closed = True
            scopes = list(self._live.values())
        for scope in scopes:
            scope.cancel("Discussion runtime shutting down")
        self._pool.shutdown(wait=False, cancel_futures=False)


class NativeSessionRPC:
    def __init__(self, turns: NativeTurns, run: Mapping[str, Any], member: Mapping[str, Any], task: Mapping[str, Any]) -> None:
        self.turns, self.run, self.member = turns, run, member
        self.task_id = task["identity"].task_id
        self.generation = int(task["execution_generation"])

    def _validate(self, profile: str, source: str, session_id: str | None = None) -> None:
        if profile != self.member["profile"] or source != "bot_room" or (session_id is not None and session_id != self.member["session_id"]):
            raise DiscussionError("session_binding_mismatch")

    def resolve_exact(self, *, profile, title, source):
        self._validate(profile, source)
        if title != "Group: " + self.run["run_id"]:
            raise DiscussionError("room_binding_mismatch")
        # Session creation is an initialization effect. Recovery never guesses a new root.
        return {"session_id": self.member["session_id"]}

    def create(self, **kwargs):
        self._validate(kwargs["profile"], kwargs["source"])
        self.turns.context.ensure_session(self.run, self.member)
        return {"session_id": self.member["session_id"]}

    def resume(self, *, profile, session_id, source):
        self._validate(profile, source, session_id)
        return {"session_id": session_id}

    def submit(self, *, profile, session_id, source, prompt, task, execution_generation, on_terminal, member_id):
        self._validate(profile, source, session_id)
        if task.task_id != self.task_id or member_id != self.member["member_id"] or task.room_id != self.run["run_id"]:
            raise DiscussionError("attempt_identity_conflict")
        self.generation = execution_generation
        row = self.turns.attempts.begin(self.run["run_id"], self.task_id, execution_generation, self.member, prompt)
        row = self.turns.recover(row)
        if row["stage"] == "terminal":
            on_terminal(row["receipt"])
        elif row["stage"] == "pending":
            self.turns.launch(self.run, self.member, row, on_terminal)
        return {"accepted": True}

    def _row(self):
        row = self.turns.attempts.get(self.run["run_id"], self.task_id, self.generation)
        return self.turns.recover(row) if row is not None else None

    def history(self, *, profile, session_id, source):
        self._validate(profile, source, session_id)
        row = self._row()
        if row is None or row["stage"] != "terminal":
            return []
        receipt = row["receipt"]
        return [{"task_id": self.task_id, "execution_generation": self.generation, "role": "assistant",
                 "status": receipt["status"], "message_id": row["native_id"],
                 "content": receipt.get("text", ""), "error": receipt.get("error")}]

    def info(self, *, profile, session_id, source):
        self._validate(profile, source, session_id)
        row = self._row()
        if row is None:
            return {"active": False, "status": "not_started", "task_id": self.task_id, "execution_generation": self.generation}
        live = self.turns.is_live(row)
        status = row["receipt"]["status"] if row["stage"] == "terminal" else row["stage"]
        # Unknown prior execution is conservatively active for cancellation: absence
        # of a process-local future does not prove a turn on another process stopped.
        return {"active": live or row["stage"] in {"pending", "waiting_input"} or not self.turns.execution_absent(row),
                "status": status, "task_id": self.task_id, "execution_generation": self.generation,
                "stop_unresolved": row["stage"] in {"running", "uncertain"}}

    def interrupt(self, *, profile, session_id, source, expected_task_id):
        self._validate(profile, source, session_id)
        if expected_task_id != self.task_id:
            raise DiscussionError("stale_stop")
        row = self._row()
        acknowledged = row is None or self.turns.interrupt(row)
        return {"interrupted": acknowledged}
