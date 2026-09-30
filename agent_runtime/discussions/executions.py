"""Select an execution adapter; both use the same room scheduler and command log."""
from __future__ import annotations

from .definitions import ParticipantRef
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

    def row(self, run_id, task):
        row = self.attempts.get(run_id, task["identity"].task_id, task["execution_generation"])
        return self.turns.recover(row) if row is not None else None

    def unresolved(self, row):
        return row is not None and (self.turns.is_live(row) or self.turns.recover(row)["stage"] != "terminal")

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
            live = self.context.resolve(ParticipantRef(member["install_id"], member["instance_id"]), run["workspace_id"])
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
