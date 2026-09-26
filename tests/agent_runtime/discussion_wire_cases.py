"""Exercise production discussion producers with a deterministic model boundary."""
from agent_runtime.discussions.contract import CONTRACT_VERSION
from agent_runtime.discussions.rpc import execute
from agent_runtime.discussions.service import DiscussionService
from tests.agent_runtime.test_discussion_definitions import table_value
from tests.agent_runtime.test_discussion_runtime import ExecutionContext, wait_until, settled


def wire_cases(tmp_path):
    context = ExecutionContext(tmp_path)
    service = DiscussionService(context, active_poll_interval=.02)
    service.start()
    def call(operation, **params):
        return {"contract_version": CONTRACT_VERSION, **execute(service, operation, params, actor_id="operator")}
    try:
        spec = table_value()
        spec["configuration"]["settings"]["allow_invitations"] = True
        preset = call("preset.save", workspace_id="ws", preset_id="engineering", expect_revision=0,
                      spec={"name": "Engineering", "preferred_capacity": "auto", "configuration": spec["configuration"]})
        call("table.save", workspace_id="ws", table_id="table", expect_revision=0, spec=spec)
        table = call("table.load_preset", workspace_id="ws", table_id="table", preset_id="engineering",
                     expect_revision=1, expect_preset_revision=1)
        run = call("run.start", workspace_id="ws", table_id="table", expect_revision=2,
                   idempotency_key="wire-start", topic="Review the architecture")["run"]
        wait_until(lambda: settled(service, run))
        cases = {"capabilities": call("capabilities"), "preset": preset, "table": table,
                 "tables": call("table.list", workspace_id="ws"), "roster": call("roster", workspace_id="ws"),
                 "runs": call("run.list", workspace_id="ws"), "presence": call("run.active", workspace_id="ws"),
                 "live": call("run.get", workspace_id="ws", run_id=run["run_id"])}
        call("run.end", workspace_id="ws", run_id=run["run_id"],
             expect_revision=cases["live"]["run"]["revision"], idempotency_key="wire-end")
        wait_until(lambda: service.view("ws", run["run_id"])["run"]["phase"] == "ended")
        cases["ended"] = call("run.get", workspace_id="ws", run_id=run["run_id"])
        room = call("run.start_room", workspace_id="ws", idempotency_key="wire-room",
                    spec={"name": "Design review", "participants": spec["configuration"]["participants"],
                          "settings": spec["configuration"]["settings"]}, topic="Review without furniture")["run"]
        wait_until(lambda: settled(service, room))
        cases["room"] = call("run.get", workspace_id="ws", run_id=room["run_id"])
        return cases
    finally:
        service.close()
