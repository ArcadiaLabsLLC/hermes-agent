"""Idempotent room commands; the run journal owns admission and completion."""
from __future__ import annotations

import logging

from gateway import hosted_room_driver as driver
from gateway import hosted_rooms as rooms
from .definitions import ParticipantRef
from .room_definition import execution_spec
from .run_values import DiscussionError

__layer__ = "lanes"

logger = logging.getLogger(__name__)


class RoomCommands:
    def __init__(self, state, runtime, context):
        self.state, self.runtime, self.context = state, runtime, context
        self.runs, self.attempts = state.runs, state.attempts
        self._processing = set()
        self._handlers = {
            "stop": self._stop, "end": self._stop, "send": self._send,
            "invite": self._invite, "remove": self._remove,
            "answer": self._answer, "retry": self._retry, "abandon": self._abandon,
        }

    def process(self, run):
        rid = run["run_id"]
        if rid in self._processing:
            return  # Terminal callbacks may re-enter while cancelling.
        self._processing.add(rid)
        try:
            pending = self.runs.pending(rid)
            pending.sort(key=lambda c: (c["operation"] not in {"stop", "end", "abandon"}, c["created_at"]))
            for cmd in pending:
                self._apply(self.runs.get(rid), cmd)
        finally:
            self._processing.discard(rid)

    def _apply(self, run, cmd):
        rid, key, op = run["run_id"], cmd["command_key"], cmd["operation"]
        try:
            self._handlers[op](run, key, cmd["body"], op)
        except (DiscussionError, ValueError) as exc:
            self.runs.finish_command(rid, key, error=getattr(exc, "reason", "operation_refused"))
        except Exception:
            # A side effect may have committed. Reconcile the same command.
            self.runs.report_error(rid, "operation_outcome_unknown")
            logger.exception("Discussion command awaits reconciliation: %s %s", rid, op)

    def _cancel(self, run, key, member_id=None):
        for task in driver.list_tasks(self.state.db_path, room_id=run["run_id"]):
            if task["status"] in {"settled", "failed", "cancelled"}:
                continue
            if member_id is not None and task["payload"]["target_member_id"] != member_id:
                continue
            self.runtime.cancel(task["identity"], cancel_id=task.get("cancel_id") or key)

    def _stop(self, run, key, body, op):
        rid = run["run_id"]
        try:
            rooms.request_room_stop(self.state.db_path, room_id=rid, cancel_id=key,
                expected_gateway_id=self.context.install_id, expected_epoch=1)
            self._cancel(run, key)
        except rooms.RoomNotFoundError:
            if self.attempts.rows(rid):
                raise
        if self.state.unresolved(rid):
            return
        refusal = self.state.finalize_room(run) if op == "end" else None
        if op == "end":
            self.runs.end(rid)
            self.context.launcher.forget(rid)
        self.runs.finish_command(rid, key, phase="paused" if op == "stop" else None)
        if refusal is not None:
            self.runs.report_error(rid, refusal)

    def _send(self, run, key, body, _op):
        if self.state.unresolved(run["run_id"]):
            return
        self.context.launcher.activate(run["run_id"], key)
        self.state.append_user(run, key, body["message"], actor_id=body["actor_id"],
                               response=body.get("response"))
        self.runs.finish_command(run["run_id"], key, phase="open")

    def _invite(self, run, key, body, _op):
        if not execution_spec(run).settings["allow_invitations"]:
            raise DiscussionError("invitations_disabled")
        live = self.context.resolve(ParticipantRef.parse(body["participant"]), run["workspace_id"])
        member = self.runs.join(run["run_id"], live)
        self.context.ensure_session(run, member)
        self.runs.set_member_status(run["run_id"], member["member_id"], "active")
        self.runs.finish_command(run["run_id"], key)

    def _remove(self, run, key, body, _op):
        rid, mid = run["run_id"], body["member_id"]
        member = next((m for m in self.runs.members(rid) if m["member_id"] == mid), None)
        if member is None:
            raise DiscussionError("member_not_found")
        if member["status"] != "removed":
            self.runs.set_member_status(rid, mid, "removing")
            self._cancel(run, key, mid)
            if self.state.unresolved(rid, mid):
                return
            self.runs.set_member_status(rid, mid, "removed")
        self.runs.finish_command(rid, key)

    def _attempt(self, run, body):
        """The command's task, its attempt row and the run's execution lane."""
        rid = run["run_id"]
        task = self.state.task(rid, body["task_id"], body["generation"])
        row = self.attempts.get(rid, body["task_id"], body["generation"])
        if row is None:
            raise DiscussionError("attempt_not_found")
        return task, row, self.state.executions.for_run(run)

    def _answer(self, run, key, body, _op):
        task, row, execution = self._attempt(run, body)
        if "group" in run["initial"]:
            raise DiscussionError("unsupported_answer")
        member = next(m for m in self.runs.members(run["run_id"]) if m["member_id"] == row["member_id"])
        execution.answer(run, member, row, key, body,
            lambda _receipt: self.runtime.request_reconciliation(task["identity"]))
        self.runs.finish_command(run["run_id"], key)

    def _retry(self, run, key, body, _op):
        task, row, execution = self._attempt(run, body)
        execution.retry(row)
        self.runtime.retry_indeterminate(task["identity"])
        self.runs.finish_command(run["run_id"], key)

    def _abandon(self, run, key, body, _op):
        task, row, execution = self._attempt(run, body)
        execution.abandon(row, body)
        self.runtime.request_reconciliation(task["identity"])
        self.runs.finish_command(run["run_id"], key)
