"""Owned spawn root, reported interpreter and identity-fenced tree accounting."""
import os
import subprocess
import sys
from types import SimpleNamespace

import psutil
import pytest

from agent_runtime.conversations import process_evidence as evidence
from agent_runtime.conversations.native_peer import NativePeer
from agent_runtime.conversations.model import ConversationError


class Process:
    def __init__(self, pid, created, rss, *, children=(), error=None):
        self.pid, self.created, self.rss = pid, created, rss
        self.descendants, self.error = children, error

    def create_time(self):
        if self.error:
            raise self.error(self.pid)
        return self.created

    def children(self, recursive):
        assert recursive
        return list(self.descendants)

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)


@pytest.fixture
def tree(monkeypatch):
    child = Process(20, 2.0, 120)
    root = Process(10, 1.0, 4, children=(child,))
    processes = {10: root, 20: child}
    monkeypatch.setattr(psutil, "Process", lambda pid: processes[pid])
    return root, child, processes


def test_stub_and_interpreter_remain_distinct_and_rss_is_tree_total(tree, monkeypatch):
    result = evidence.observe_process_tree((10, 1.0))
    assert result.root == (10, 1.0)
    assert result.identities == ((10, 1.0), (20, 2.0))
    assert result.rss_bytes == 124
    assert result.status is evidence.TreeStatus.COMPLETE
    peer = NativePeer.__new__(NativePeer)
    peer.launcher_identity, peer._worker_identity = (10, 1.0), None
    peer._worker_purpose = "native-conversation"
    registered = []
    monkeypatch.setattr("hermes_cli.process_identity.register_child", lambda pid, purpose: registered.append((pid, purpose)))
    peer.bind_worker_identity({"worker_pid": 20, "worker_created": 2.0})
    assert peer.process_identity == (20, 2.0)
    assert registered == [(20, "native-conversation")]
    assert peer.launcher_identity == (10, 1.0)


def test_root_pid_reuse_discards_entire_tree(tree):
    root, _, _ = tree
    root.created = 8.0
    result = evidence.observe_process_tree((10, 1.0))
    assert result.status is evidence.TreeStatus.ROOT_REUSED
    assert result.identities == () and result.rss_bytes is None


def test_descendant_exit_does_not_become_zero_or_complete(tree):
    _, child, _ = tree
    child.error = psutil.NoSuchProcess
    result = evidence.observe_process_tree((10, 1.0))
    assert result.identities == ((10, 1.0),)
    assert result.rss_bytes is None
    assert result.status is evidence.TreeStatus.PARTIAL


def test_unavailable_child_identity_cannot_bind_worker(tree):
    _, child, _ = tree
    child.error = psutil.AccessDenied
    peer = NativePeer.__new__(NativePeer)
    peer.launcher_identity, peer._worker_identity = (10, 1.0), None
    with pytest.raises(ConversationError):
        peer.bind_worker_identity({"worker_pid": 20, "worker_created": 2.0})
    with pytest.raises(ConversationError):
        _ = peer.process_identity


def test_reported_child_creation_time_must_match(tree):
    peer = NativePeer.__new__(NativePeer)
    peer.launcher_identity, peer._worker_identity = (10, 1.0), None
    with pytest.raises(ConversationError):
        peer.bind_worker_identity({"worker_pid": 20, "worker_created": 9.0})


def test_descendant_pid_reused_during_rss_read_is_omitted(tree, monkeypatch):
    root, child, processes = tree
    replacement = Process(20, 9.0, 999)
    def memory():
        processes[20] = replacement
        return SimpleNamespace(rss=120)
    monkeypatch.setattr(child, "memory_info", memory)
    result = evidence.observe_process_tree((10, 1.0))
    assert result.identities == ((10, 1.0),)
    assert result.rss_bytes is None and result.status is evidence.TreeStatus.PARTIAL


def test_unavailable_root_is_typed_and_unknown(monkeypatch):
    def denied(pid):
        raise psutil.AccessDenied(pid)
    monkeypatch.setattr(psutil, "Process", denied)
    result = evidence.observe_process_tree((10, 1.0))
    assert result.status is evidence.TreeStatus.UNAVAILABLE
    assert result.rss_bytes is None and result.identities == ()


@pytest.mark.timeout(30)
def test_real_selected_venv_interpreter_receipt_and_tree():
    code = """import json,sys
from agent_runtime.conversations.process_evidence import worker_ready_frame
print(json.dumps(worker_ready_frame()),flush=True)
for line in sys.stdin:
    request=json.loads(line)
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'ready':True}}),flush=True)
"""
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    process = subprocess.Popen([sys.executable, "-u", "-c", code], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **options)
    peer = NativePeer(process, receive=lambda frame: None, lost=lambda: None)
    try:
        assert peer.call("identity.test", {}) == {"ready": True}
        identity = peer.process_identity
        tree = evidence.observe_process_tree(peer.launcher_identity)
        assert identity in tree.identities
        assert tree.status is evidence.TreeStatus.COMPLETE and tree.rss_bytes > 0
        if sys.platform == "win32" and sys.prefix != sys.base_prefix:
            assert identity[0] != process.pid
            assert len(tree.identities) >= 2
        assert identity[0] != os.getpid()
    finally:
        peer.close()
    assert not peer.execution_possible


def test_launcher_exit_does_not_prove_interpreter_exit(tree, monkeypatch):
    _, child, _ = tree
    peer = NativePeer.__new__(NativePeer)
    peer.process = SimpleNamespace(poll=lambda: 0)
    peer._worker_identity = (20, 2.0)
    monkeypatch.setattr(Process, "status", lambda self: psutil.STATUS_RUNNING, raising=False)
    assert peer.execution_possible
    child.created = 9.0
    assert not peer.execution_possible
    child.created, child.error = 2.0, psutil.NoSuchProcess
    assert not peer.execution_possible
    peer._worker_identity = None
    assert not peer.execution_possible
