"""Discussion tasks over the existing native conversation owner, without new workers."""
from __future__ import annotations

import os
import threading

from agent_runtime.conversations.model import ConversationError
from .profile_groups import member_scope
from .run_values import DiscussionError

__layer__ = "lanes"

_OUTCOMES = {"complete": "settled", "interrupted": "cancelled", "error": "failed"}


class ProfileTurns:
    def __init__(self, context, attempts, runs, conversations=None):
        from agent_runtime.conversations.binding import get_service
        from gateway.status import get_process_start_time

        self.context, self.attempts, self.runs = context, attempts, runs
        self._service = conversations or get_service
        self._admission = threading.RLock()
        self._closed = False
        self.pid, self.started = os.getpid(), get_process_start_time(os.getpid())
        if self.started is None:
            raise DiscussionError("process_identity_unavailable")

    def _binding(self, row):
        run = self.runs.get(row["run_id"])
        member = next(m for m in self.runs.members(row["run_id"]) if m["member_id"] == row["member_id"])
        return run, member, member_scope(run, member)

    def _current(self, row):
        return self.attempts.get(row["run_id"], row["task_id"], row["generation"]) or row

    def launch(self, run, member, row, on_terminal=None):
        # Cancellation fences this short admission, not the independently running model turn.
        with self._admission:
            if self._closed:
                raise DiscussionError("runtime_stopping")
            if not self.attempts.claim(row, pid=self.pid, started=self.started):
                return
            dispatched = False
            try:
                service, scope = self._service(), member_scope(run, member)
                opened = service.open(scope, key=run["run_id"], cwd=run["initial"]["group"]["cwd"],
                                      expected_home=member["binding"]["home"])
                if opened["session_id"] != row["session_id"]:
                    raise DiscussionError("session_binding_mismatch")
                dispatched = True
                service.send(scope, row["session_id"], row["native_id"], {"text": row["prompt"], "images": []})
            except Exception as exc:
                if dispatched:
                    self.attempts.update(row, stage="uncertain")
                else:
                    self.attempts.update(row, stage="terminal", receipt={"status": "failed", "text": "",
                        "error": str(getattr(exc, "reason", "profile_unavailable")), "message_id": row["native_id"]})
            current = self.recover(row)
        if current["stage"] == "terminal" and on_terminal is not None:
            on_terminal(current["receipt"])

    def recover(self, row):
        with self._admission:
            return self._recover(row)

    def _recover(self, row):
        current = self._current(row)
        if current["stage"] in {"pending", "terminal"}:
            return current
        try:
            _, _, scope = self._binding(current)
            snapshot = self._service().observe_execution(scope, current["session_id"], current["native_id"])
            self._project(current, snapshot)
        except (ConversationError, OSError, RuntimeError):
            self.attempts.update(current, stage="uncertain")
        return self._current(current)

    def _project(self, row, snapshot):
        if snapshot.get("admitted") is False:
            self.attempts.update(row, stage="terminal", receipt={"status": "failed", "text": "",
                "error": "dispatch_not_admitted", "message_id": row["native_id"]})
            return
        native = snapshot["recovery"].get("execution") or {}
        expected = (snapshot.get("turn") or {}).get("execution_id")
        if not expected or native.get("id") != expected:
            self.attempts.update(row, stage="uncertain")
            return
        status, result = native.get("status"), native.get("result")
        if status in _OUTCOMES:
            if status == "complete" and not isinstance(result, dict):
                self.attempts.update(row, stage="uncertain")
                return
            self.attempts.update(row, stage="terminal", receipt={"status": _OUTCOMES[status],
                "text": (result or {}).get("text", ""), "error": (result or {}).get("error"),
                "message_id": row["native_id"], "settlement_id": expected})
            return
        requests = snapshot.get("requests") or []
        question = {"request": requests[0]} if requests else None
        stage = "waiting_input" if question else ("running" if status == "running" else "uncertain")
        self.attempts.update(row, stage=stage, question=question)

    def is_live(self, row):
        return self.recover(row)["stage"] in {"running", "waiting_input"}

    def execution_absent(self, row):
        return self.recover(row)["stage"] in {"pending", "terminal"}

    def interrupt(self, row):
        with self._admission:
            current = self._current(row)
            if current["stage"] == "pending":
                self.attempts.update(current, stage="terminal", receipt={"status": "cancelled", "text": ""})
                return True
            if current["stage"] == "terminal":
                return True
            _, _, scope = self._binding(current)
            try:
                self._service().stop(scope, current["session_id"], current["native_id"])
            except ConversationError:
                return False
            return self.recover(current)["stage"] == "terminal"

    def answer(self, row, body):
        if body["native_id"] != row["native_id"]:
            raise DiscussionError("stale_attempt")
        _, _, scope = self._binding(row)
        accepted = self._service().respond(scope, row["session_id"], body["request_id"], body["result"])
        if not accepted.get("accepted"):
            raise DiscussionError("answer_not_acknowledged")
        self.recover(row)

    def abandon(self, row):
        # Uncertain profile work belongs to ConversationService, never a process guess here.
        if not self.execution_absent(row):
            raise DiscussionError("execution_still_live")

    def close(self):
        with self._admission:
            self._closed = True
