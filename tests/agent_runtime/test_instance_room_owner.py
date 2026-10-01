"""Account isolation through real RPC dispatch, run admission and SessionDB."""
from contextlib import closing

import pytest

from agent_runtime import serve_rpc
from agent_runtime.conversation_owner import session_client_scope
from agent_runtime.discussions import service as service_module
from agent_runtime.call_authorization import LOCAL_CONSOLE
from hermes_state import SessionDB
from tests.agent_runtime.test_discussion_runtime import engine as engine, wait_until
from tests.agent_runtime.test_native_discussion_room import spec
from tests.agent_runtime.test_serve_rpc_open_chat import _device

OWNER, OTHER = "a" * 64, "b" * 64
pytestmark = pytest.mark.timeout(90)


@pytest.fixture
def room_rpc(engine, monkeypatch):
    service, context = engine
    monkeypatch.setattr(service_module, "_owner", service)

    def call(action, *, caller=LOCAL_CONSOLE, **params):
        return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "test",
            "method": "runtime.discussion.run." + action, "params": {"workspace_id": "ws", **params}},
            serve_rpc.RpcContext(caller=caller))

    return service, context, call


def create(call, owner, *, key="new", name="Review"):
    return call("start_room", spec={**spec().to_dict(), "name": name},
                idempotency_key=key, topic="", **({"client_scope": owner} if owner else {}))


def test_empty_rooms_are_retry_stable_account_owned_and_do_not_start_turns(room_rpc):
    service, context, call = room_rpc
    first = create(call, OWNER)["result"]["run"]
    second = create(call, OTHER)["result"]["run"]
    assert first["run_id"] != second["run_id"]
    assert create(call, OWNER)["result"]["run"]["run_id"] == first["run_id"]
    assert create(call, OWNER, name="Changed")["error"]["data"]["reason"] == "idempotency_conflict"
    wait_until(lambda: all(service.runs.get(r["run_id"])["phase"] == "open" for r in (first, second)))
    assert context.calls == []
    with closing(SessionDB(db_path=context.home / "state.db", read_only=True)) as db:
        for run, owner in ((first, OWNER), (second, OTHER)):
            for member in service.runs.members(run["run_id"]):
                assert session_client_scope(db.get_session(member["session_id"])) == owner
    assert call("get", run_id=first["run_id"], client_scope=OWNER)["result"]["run"]["run_id"] == first["run_id"]
    assert call("get", run_id=first["run_id"], client_scope=OTHER)["error"]["data"]["reason"] == "conversation_owner_changed"


def test_pagination_filters_before_limiting_and_console_can_inspect_all(room_rpc):
    _, _, call = room_rpc
    mine = {create(call, OWNER, key=str(i))["result"]["run"]["run_id"] for i in range(3)}
    others = {create(call, OTHER, key=str(i))["result"]["run"]["run_id"] for i in range(3)}
    found, cursor = set(), None
    while True:
        page = call("list", client_scope=OWNER, limit=1, **({"after": cursor} if cursor else {}))["result"]
        found.update(row["run_id"] for row in page["runs"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert found == mine
    all_rows = call("list")["result"]["runs"]
    assert {row["run_id"] for row in all_rows} == mine | others
    assert {row["initial"]["client_scope"] for row in all_rows} == {OWNER, OTHER}
    assert {row["run"]["run_id"] for row in call("active", client_scope=OWNER)["result"]["rooms"]} == mine


def test_read_only_device_cannot_use_digest_as_a_credential(room_rpc):
    _, _, call = room_rpc
    owned = create(call, OWNER)["result"]["run"]
    legacy = create(call, None)["result"]["run"]
    for scope in ({}, {"client_scope": OWNER}):
        reply = call("get", run_id=owned["run_id"], caller=_device("read"), **scope)
        assert reply["error"]["data"]["reason"] == "console_required"
    rows = call("list", caller=_device("read"))["result"]["runs"]
    assert [row["run_id"] for row in rows] == [legacy["run_id"]]
    assert call("get", run_id=legacy["run_id"], caller=_device("read"))["result"]["run"]["run_id"] == legacy["run_id"]


@pytest.mark.parametrize("operation,body", [("send", {"message": "hello"}), ("stop", {}), ("end", {})])
def test_wrong_owner_commands_cannot_mutate_or_start_work(room_rpc, operation, body):
    service, context, call = room_rpc
    run = create(call, OWNER)["result"]["run"]
    wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "open")
    before = service.runs.get(run["run_id"])
    reply = call(operation, run_id=run["run_id"], client_scope=OTHER,
                 expect_revision=before["revision"], idempotency_key="command", **body)
    assert reply["error"]["data"]["reason"] == "conversation_owner_changed"
    assert service.runs.get(run["run_id"]) == before
    assert context.calls == []
