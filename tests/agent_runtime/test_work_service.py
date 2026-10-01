"""Real native storage proves Work is a projection, not another task engine."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from agent_runtime.call_authorization import LOCAL_CONSOLE, STDIO_OWNER, UNKNOWN_CALLER
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.work import native, service
from agent_runtime.work.model import Reason, WorkRefused
from hermes_cli import kanban_db as tasks
from hermes_cli.kanban_db_connect import connect_closing


@pytest.fixture
def work(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("model: {}\n")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    root = tmp_path / "runtime"
    monkeypatch.setattr(service, "store_root", lambda: root)
    ensure_install_identity(root)
    capabilities = service.execute("capabilities", {}, STDIO_OWNER)
    owner = next(row for row in capabilities["owners"] if row["profile"] == "default" and row["board"] == "default")
    scope = {"install_id": capabilities["install_id"], "owner": owner["owner"]}
    return scope, home


def start(scope, **overrides):
    params = {**scope, "client_scope": "account", "request_id": "request-1", "title": "Review", "body": "Review the change."}
    return service.execute("start", {**params, **overrides}, STDIO_OWNER)


def test_create_inspect_and_list_keep_native_identity(work):
    scope, home = work
    assert not (home / "kanban.db").exists()
    assert service.execute("list", scope, STDIO_OWNER)["tasks"] == []
    assert not (home / "kanban.db").exists()
    receipt = start(scope)
    task_id = receipt["task"]["id"]
    with connect_closing(board="default") as conn:
        task = tasks.get_task(conn, task_id)
        assert task.status == "ready"
        assert task.body == "Review the change."
        assert task.assignee == "default"
        assert task.workspace_kind == "scratch"
    read = service.execute("inspect", {**scope, "task_id": task_id}, STDIO_OWNER)
    assert read["task"] == receipt["task"]
    assert service.execute("list", scope, STDIO_OWNER)["tasks"][0]["id"] == task_id


def test_concurrent_retry_admits_one_native_task(work):
    scope, _ = work
    barrier = Barrier(6)
    def send(_):
        barrier.wait()
        return start(scope)["task"]["id"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(send, range(6)))
    assert len(set(ids)) == 1
    with connect_closing(board="default") as conn:
        assert len(tasks.list_tasks(conn)) == 1


def test_replay_rejects_changed_payload_and_keeps_archived_identity(work):
    scope, _ = work
    receipt = start(scope)
    with pytest.raises(WorkRefused, match=Reason.CONFLICT):
        start(scope, body="Different request")
    with connect_closing(board="default") as conn:
        tasks.archive_task(conn, receipt["task"]["id"])
    archived = start(scope)
    assert archived["task"]["id"] == receipt["task"]["id"]
    assert archived["task"]["status"] == "archived"


def test_scope_and_profile_changes_refuse_without_retargeting(work, monkeypatch):
    scope, home = work
    with pytest.raises(WorkRefused, match=Reason.OWNER_CHANGED):
        start({**scope, "install_id": "other"})
    with pytest.raises(WorkRefused, match=Reason.OWNER_CHANGED):
        start({**scope, "owner": "other"})
    assert not (home / "kanban.db").exists()
    task_id = start(scope)["task"]["id"]
    with connect_closing(board="default") as conn:
        tasks.assign_task(conn, task_id, "different")
    with pytest.raises(WorkRefused, match=Reason.OWNER_CHANGED):
        service.execute("inspect", {**scope, "task_id": task_id}, STDIO_OWNER)
    assert service.execute("list", scope, STDIO_OWNER)["tasks"] == []
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home / "another"))
    with pytest.raises(WorkRefused, match=Reason.OWNER_CHANGED):
        start(scope)


def test_private_service_refuses_unknown_caller_and_scopes_request_keys(work):
    scope, _ = work
    for operation in ("capabilities", "list", "inspect", "start"):
        with pytest.raises(WorkRefused, match=Reason.DENIED):
            service.execute(operation, scope, UNKNOWN_CALLER)
    first = start(scope)["task"]["id"]
    same = service.execute("start", {**scope, "client_scope": "account", "request_id": "request-1",
                                    "title": "Review", "body": "Review the change."}, LOCAL_CONSOLE)
    assert same["task"]["id"] == first
    assert start(scope, client_scope="another-account")["task"]["id"] != first


def test_keyset_pages_do_not_duplicate_or_skip_existing_work(work):
    scope, _ = work
    with connect_closing(board="default") as conn:
        expected = {tasks.create_task(conn, title=f"Task {i}", assignee="default", workspace_kind="scratch", board="default")
                    for i in range(native.PAGE_SIZE + 3)}
    first = service.execute("list", scope, STDIO_OWNER)
    assert len(first["tasks"]) == native.PAGE_SIZE
    second = service.execute("list", {**scope, "cursor": first["cursor"]}, STDIO_OWNER)
    ids = [row["id"] for row in first["tasks"] + second["tasks"]]
    assert len(ids) == len(set(ids))
    assert set(ids) == expected
    assert second["cursor"] is None


def test_inspection_bounds_results_and_preserves_unknown_states(work):
    scope, _ = work
    task_id = start(scope)["task"]["id"]
    with connect_closing(board="default") as conn:
        task = tasks.get_task(conn, task_id)
    task.result = "a" * (native.OUTPUT_LIMIT + 1)
    task.status = "future-state"
    projection = native.project(task, detail=True)
    assert projection["status"] == "future-state"
    assert len(projection["result"]) == native.OUTPUT_LIMIT
    assert projection["result_truncated"] is True
