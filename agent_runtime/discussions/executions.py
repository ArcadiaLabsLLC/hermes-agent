"""Select an execution adapter; both use the same room scheduler and command log."""
from __future__ import annotations

from .native import NativeTurns
from .session_rpc import NativeSessionRPC
from .run_values import DiscussionError

__layer__ = "lanes"


class SessionExecution:
    def __init__(self, context, attempts, turns):
        self.context, self.attempts = context, attempts
        self.turns = turns

    def transport(self, run, member, task):
        return NativeSessionRPC(self.turns, run, member, task)

    def row(self, run_id, task, attempts=None):
        """``task``'s attempt, recovered. ``attempts`` is the run's ``attempt_rows``, read once for a whole
        walk over its tasks; without it this reads the one row. Either way the row is fresh, so recovery
        does not read it again (a view over twelve tasks opened the attempt file 24 times)."""
        key = (task["identity"].task_id, task["execution_generation"])
        row = attempts.get(key) if attempts is not None else self.attempts.get(run_id, *key)
        return self.turns.recover(row, fresh=True) if row is not None else None

    def attempt_rows(self, run_id):
        """Every attempt of ``run_id`` on ONE connection, keyed ``(task_id, generation)`` for ``row``."""
        return {(row["task_id"], row["generation"]): row for row in self.attempts.rows(run_id)}

    def unresolved(self, row):
        """``row`` comes from ``row`` (recovered from a fresh read), so its re-check does not read it again."""
        return row is not None and (self.turns.is_live(row) or self.turns.recover(row, fresh=True)["stage"] != "terminal")

    def retry(self, row):
        if not self.turns.execution_absent(row):
            raise DiscussionError("execution_still_live")

    def abandon(self, row, body):
        if body["native_id"] != row["native_id"]:
            raise DiscussionError("stale_attempt")
        self.turns.abandon(row)


class InstanceExecution(SessionExecution):
    def __init__(self, context, attempts):
        super().__init__(context, attempts, NativeTurns(context, attempts))

    def initialize(self, run, members):
        for member in members:
            if run["table_id"] is not None:
                live = self.context.resolve_member(run, member)
                if any(live[k] != member[k] for k in ("persona_id", "profile")):
                    raise DiscussionError("profile_binding_changed")
            self.context.ensure_session(run, member)

    def answer(self, run, member, row, key, body, callback):
        row = self.attempts.answer(run["run_id"], body["task_id"], body["generation"],
            expected_native_id=body["native_id"], key=key, answer=body["answer"])
        self.turns.launch(run, member, row, callback)


class ProfileExecution(SessionExecution):
    def __init__(self, context, attempts, runs, conversations):
        from .profile_turns import ProfileTurns

        super().__init__(context, attempts, ProfileTurns(context, attempts, runs, conversations))

    def initialize(self, run, members):
        # Opening a group does not launch workers or depend on every route being online.
        return None

class Executions:
    def __init__(self, context, attempts, runs, conversations=None):
        self.instances = InstanceExecution(context, attempts)
        self.profiles = ProfileExecution(context, attempts, runs, conversations)

    def for_run(self, run):
        return self.profiles if "group" in run["initial"] else self.instances

    def close(self):
        self.instances.turns.close()
        self.profiles.turns.close()
