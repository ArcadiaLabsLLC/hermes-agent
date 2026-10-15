"""Instance-bound turns over the native Mission Control execution lane."""
from __future__ import annotations

import contextvars
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, Mapping

from agent.interrupt_scope import InterruptScope, bind_interrupt_scope
from agent_runtime.auxiliary_chat import auxiliary_chat
from .attempt_store import AttemptStore
from .native_context import NativeContext
from .run_values import DiscussionError

__layer__ = "stores"

log = logging.getLogger(__name__)


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
            from .app_functions import discussion_launcher
            request = self.context.launcher.request_for(run["run_id"], row["task_id"])
            with self.context.scope(), auxiliary_chat(member["instance_id"], member["session_id"]), bind_interrupt_scope(scope), discussion_launcher(request):
                live = self.context.resolve_member(run, member)
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
            self._returned(row, scope, code, payloads[-1] if payloads else {})
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

    def _returned(self, row, scope, code, payload):
        if self.recover(row)["stage"] in {"terminal", "waiting_input"}:
            return
        uncertain = payload.get("turn_resolution_required") or payload.get("execution_state") == "outcome_unknown"
        if not code or uncertain:
            self.attempts.update(row, stage="uncertain")
            return
        # Returning from the exact interrupted worker confirms exit; requesting Stop did not.
        stopped = scope.reason is not None
        self.attempts.update(row, stage="terminal", receipt={
            "status": "cancelled" if stopped else "failed", "text": "",
            "error": None if stopped else str(payload.get("error_kind") or "native_turn_refused"),
            "message_id": row["native_id"]})

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
        except ImportError:  # no psutil (the phone profile omits it): no stamp to compare, liveness unproven
            return False
        try:
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
