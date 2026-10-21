"""The socket-owner record and the register row name the INSTALL that serves the store
(row RT-NAMESPACE-OWNER-INSTALL-STAMP; launcher plan EDITION_SWITCH_NAMESPACE_STORE §2.2, §4).

Both editions open one shared namespace, so the store no longer says which edition is serving it.
Every owner record and ``serve_instances`` row carries ``install {base_root, edition}``, and a
contender that finds a live owner reports ``lock_held_by`` with ``owner_install`` — the launcher's
"still running this account's agents" refusal reads it. The takeover-on-drain rule is untouched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_runtime.namespace import install_stamp
from agent_runtime.serve_registry import list_serve_instances, register_serve_instance
from agent_runtime.serve_socket.owner_lock import SocketOwnerLock, read_socket_owner, socket_owner_path
from agent_runtime.serve_socket.vocabulary import LOCK_OUTCOME_HELD


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("HERMES_NAMESPACE", raising=False)
    monkeypatch.setenv("HERMES_DEPENDENCY_ROOT", str(tmp_path / "dev-install" / ".hermes"))
    return tmp_path / "agent-runtime"


def test_the_install_stamp_names_the_base_root_and_the_edition(store: Path, tmp_path: Path):
    assert install_stamp() == {"base_root": str(tmp_path / "dev-install" / ".hermes"), "edition": "developer"}


def test_a_contender_reads_the_live_owners_install(store: Path, tmp_path: Path, monkeypatch):
    owner = SocketOwnerLock(store)
    assert owner.acquire().acquired
    try:
        owner.publish_owner({"pid": os.getpid(), "port": 5, "started_at": "t"})
        register_serve_instance(store, pid=os.getpid(), boot_id="b")  # a live owner, not a leaving one
        published = {"base_root": str(tmp_path / "dev-install" / ".hermes"), "edition": "developer"}
        assert read_socket_owner(store)["install"] == published
        # The contender is another install: its own stamp differs, and it reports the OWNER's.
        monkeypatch.setenv("HERMES_DEPENDENCY_ROOT", str(tmp_path / "bundled" / ".hermes"))
        result = SocketOwnerLock(store).acquire()
        assert result.outcome == LOCK_OUTCOME_HELD
        assert result.owner_install == published
        assert result.payload()["owner_install"] == published
    finally:
        owner.release()


def test_the_register_row_carries_the_install(store: Path, tmp_path: Path):
    register_serve_instance(store, pid=424242, boot_id="b")
    (row,) = [r for r in list_serve_instances(store) if r.get("pid") == 424242]
    assert row["install"] == {"base_root": str(tmp_path / "dev-install" / ".hermes"), "edition": "developer"}


def test_a_pre_stamp_owner_reports_no_install(store: Path):
    owner = SocketOwnerLock(store)
    assert owner.acquire().acquired
    try:
        socket_owner_path(store).write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        assert read_socket_owner(store)["pid"] == os.getpid()  # the record is there, without `install`
        result = SocketOwnerLock(store).acquire()
        assert result.outcome == LOCK_OUTCOME_HELD and result.owner_install is None
        assert "owner_install" not in result.payload()
    finally:
        owner.release()
