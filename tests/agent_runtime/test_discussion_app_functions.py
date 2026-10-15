"""Admitted group task -> native tool relay -> actual Launcher wire provenance."""
from agent_runtime import launcher_app_functions as laf
from agent_runtime.conversations.worker_app_functions import METHOD
from agent_runtime.discussions.app_functions import requesting_launcher
from tests.agent_runtime.test_discussion_profile_groups import (
    act, complete, create, groups, idle, sends, wait_until,
)
from tests.agent_runtime.test_launcher_app_functions import _Launcher


def test_group_tools_use_public_task_identity_and_original_connection(groups):
    service, _, factory, _ = groups
    sink = _Launcher()
    link = laf.LauncherLink(sink, laf.ORIGIN_LOCAL)
    with requesting_launcher(link.request):
        run = create(groups)
        member = service.runs.members(run["run_id"])[0]["member_id"]
        act(service, run, "send", "first", message="Build a calculator", response={"mode": "reply", "members": [member]})
    wait_until(lambda: len(sends(factory)) == 1)
    worker, prompt = sends(factory)[0]
    view = service.view(run["workspace_id"], run["run_id"])
    task = view["tasks"][0]
    with requesting_launcher(lambda *_: (_ for _ in ()).throw(AssertionError("retargeted"))):
        create(groups)
    worker.question(prompt["session_id"], "generated-1", method=METHOD,
                    request={"method": "launcher.generated.create", "params": {
                        "_meta": {"invocation": {"session_id": "forged"}}}})
    wait_until(lambda: any(f.get("method") == "launcher.generated.create" for f in sink.sent))
    wire = next(f for f in sink.sent if f.get("method") == "launcher.generated.create")
    assert wire["params"]["_meta"]["invocation"] == {
        "channel": "discussion", "session_id": run["run_id"],
        "turn_id": task["task_id"], "client_scope": "account"}
    wait_until(lambda: any(f.get("id") == "generated-1" for f in worker.writes))
    worker.question(prompt["session_id"], "generated-1", method=METHOD,
                    request={"method": "launcher.generated.create", "params": {}})
    assert len([f for f in sink.sent if f.get("method") == "launcher.generated.create"]) == 1
    complete(factory)
    wait_until(lambda: idle(service, run, 1))
    new_sink = _Launcher()
    with requesting_launcher(laf.LauncherLink(new_sink, laf.ORIGIN_LOCAL).request):
        act(service, run, "send", "second", message="Build snake", response={"mode": "reply", "members": [member]})
    wait_until(lambda: len(sends(factory)) == 2)
    worker, prompt = sends(factory)[-1]
    worker.question(prompt["session_id"], "generated-2", method=METHOD,
                    request={"method": "launcher.generated.create", "params": {}})
    wait_until(lambda: any(f.get("method") == "launcher.generated.create" for f in new_sink.sent))
    wire = next(f for f in new_sink.sent if f.get("method") == "launcher.generated.create")
    assert wire["params"]["_meta"]["invocation"]["turn_id"] != task["task_id"]
    assert len([f for f in sink.sent if f.get("method") == "launcher.generated.create"]) == 1
    complete(factory)
