"""Exact room-task transport over either native execution adapter."""
from __future__ import annotations

from typing import Any, Mapping
from .run_values import DiscussionError

__layer__ = "lanes"


class NativeSessionRPC:
    def __init__(self, turns, run: Mapping[str, Any], member: Mapping[str, Any], task: Mapping[str, Any]) -> None:
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
        # Membership supplies the exact session; transports never create replacement identities.
        raise DiscussionError("session_not_initialized")

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
