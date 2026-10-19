"""Every serve record names its store's namespace (row RT-NAMESPACE-STAMP).

The id rides the socket-owner record, the ``serve_instances`` row, the ready frame, every serve
service-log line and every work-store receipt line: ``""`` for the base root, the id otherwise —
never the account subject. A sweep judges a serve by this stamp, because install anchors are the
same for every namespace of one install (plan §2.5).
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

from agent_runtime.serve_registry import list_serve_instances, register_serve_instance
from agent_runtime.serve_socket.owner_lock import SocketOwnerLock, read_socket_owner, socket_owner_path
from agent_runtime.work_store import receipts
from hermes_cli import _namespace_bootstrap as ns_boot

NS = "acct-0123456789abcdef"


@pytest.fixture
def namespaced(tmp_path: Path, monkeypatch) -> Path:
    """This process runs in namespace NS; returns its store root (inside the namespace)."""
    monkeypatch.setattr(ns_boot, "long_paths_enabled", lambda: True)
    root = tmp_path / "hermes-namespaces" / NS
    monkeypatch.setenv("HERMES_NAMESPACE", NS)
    monkeypatch.setenv("HERMES_DEPENDENCY_ROOT", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_NAMESPACES_DIR", str(tmp_path / "hermes-namespaces"))
    monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "base"))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root / "agent-runtime"))
    monkeypatch.delenv("HERMES_HEAD_HOME", raising=False)
    return root / "agent-runtime"


def test_the_owner_record_carries_the_namespace_and_the_reader_exposes_it(namespaced: Path, monkeypatch):
    lock = SocketOwnerLock(namespaced)
    assert lock.acquire().acquired
    try:
        lock.publish_owner({"pid": 1, "port": 5})
        raw = json.loads(socket_owner_path(namespaced).read_text(encoding="utf-8"))
        assert raw["namespace"] == NS and raw["port"] == 5
        assert read_socket_owner(namespaced)["namespace"] == NS
        monkeypatch.delenv("HERMES_NAMESPACE")
        lock.publish_owner({"pid": 1, "port": 5})
        assert json.loads(socket_owner_path(namespaced).read_text(encoding="utf-8"))["namespace"] == ""
    finally:
        lock.release()


def test_a_record_that_predates_the_stamp_reads_as_the_base_root(tmp_path: Path):
    socket_owner_path(tmp_path).write_text(json.dumps({"pid": 7}), encoding="utf-8")
    assert read_socket_owner(tmp_path) == {"pid": 7, "namespace": ""}


def test_the_register_row_carries_the_namespace(namespaced: Path):
    register_serve_instance(namespaced, pid=424242, boot_id="b")
    (row,) = [r for r in list_serve_instances(namespaced) if r.get("pid") == 424242]
    assert row["namespace"] == NS


def test_the_ready_frame_names_its_namespace(namespaced: Path):
    from hermes_cli.harness_parts.serve import serve_loop

    out = io.StringIO()
    serve_loop(iter([json.dumps({"op": "shutdown"}) + "\n"]), out, dispatch=lambda argv: 0)
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line]
    (ready,) = [frame for frame in frames if frame.get("event") == "ready"]
    assert ready["namespace"] == NS
    assert ready["runtime_root"] == str(namespaced)


def test_service_log_lines_and_receipts_name_the_namespace(namespaced: Path, capsys, caplog):
    from hermes_cli.harness_parts.serve.session import ServeSession

    ServeSession._service_log(object(), {"event": "serve_socket_owner_stale", "pid": 1})
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["namespace"] == NS and line["event"] == "serve_socket_owner_stale"
    with caplog.at_level(logging.INFO, logger=receipts.logger.name):
        record = receipts.emit("schedule.fire", key="k")
    assert json.loads(caplog.records[-1].getMessage())["namespace"] == NS
    assert "namespace" not in record  # the returned record's shape is unchanged; the log line is the receipt
