"""A device driving this engine opens the diffs and context files its agent wrote, by handle.

Row ``RT-FU-A-DEVICE-DRIVING-THIS-ENGINE-OPENS-THE-DIFFS-AND-CONTEXT-FILES-ITS-AGENT-WROTE``. The
real writers make the files: ``record_patch_diff`` writes the diff a trace names, and a
prompt-context frame (the persisted row ``load_latest_prompt_observability_contexts`` reads) lists
the context files a turn loaded. ``runtime.media.index`` / ``.get`` are called through the real
dispatcher, with the caller the transport would stamp. Every test runs in the ``tests/agent_runtime``
conftest's isolated store root.

Killing mutations (each red seen 2026-11-22):

* ``media_handles.build_media_scope``: skip ``_fold_agent_files`` and the driving-device test finds
  no diff or context-file row;
* ``agent_file_handles.SERVED_CONTEXT_FILE_NAMES``: add ``config.yaml`` and the config test finds
  its handle in the index and its bytes served;
* ``media_handles.build_media_scope``: default ``agent_files`` to ``True`` and the peer keyhole serves
  a diff to a paired install;
* ``agent_file_handles._DIFF_NAME_RE``: match any name and a stray file dropped beside the diffs is
  offered.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from agent_runtime import chat_live_log, media_handles, paths, serve_rpc
from agent_runtime.call_authorization import (
    CALLER_DEVICE,
    CALLER_PEER,
    REASON_SCOPE_DENIED,
    STDIO_OWNER,
    TIER_CONSOLE,
    TIER_READ,
    TRANSPORT_GATEWAY,
    RpcCaller,
)
from agent_runtime.patch_diff_artifacts import record_patch_diff

INDEX = "runtime.media.index"
GET = "runtime.media.get"

_DIFF = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old = 1\n+new = 2\n"


def _device(tier: str) -> RpcCaller:
    return RpcCaller(kind=CALLER_DEVICE, connection_key="c1", transport=TRANSPORT_GATEWAY,
                     device_id="dev_phone", device_tier=tier)


def _call(method: str, params: dict | None = None, *, caller=STDIO_OWNER) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "m1", "method": method, "params": params or {}},
                                    serve_rpc.RpcContext(caller=caller, transport=TRANSPORT_GATEWAY))


def _handle(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture
def written(tmp_path):
    """A patch call's diff and one turn's context files, written where the runtime writes them."""

    chat_live_log.reset_chat_live_log_state()
    media_handles.reset_digest_memo()
    fields = record_patch_diff({"success": True, "diff": _DIFF})
    assert fields is not None
    profile = tmp_path / "profile"
    workspace = tmp_path / "workspace"
    profile.mkdir()
    workspace.mkdir()
    files = {
        "soul": (profile / "SOUL.md", b"# Soul\nbe kind\n"),
        "agents": (workspace / "AGENTS.md", b"# Rules\nrun the tests\n"),
        "skills": (profile / ".skills_prompt_snapshot.json", b'{"skills": ["triage"]}'),
        "config": (profile / "config.yaml", b"model:\n  api_key: sk-secret-never-served\n"),
        "memory": (profile / "memories" / "MEMORY.md", b"remember this\n"),
    }
    for path, data in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    frames = paths.prompt_observability_dir()
    frames.mkdir(parents=True, exist_ok=True)
    (frames / "ctx_one.json").write_text(json.dumps({
        "context_id": "ctx_one",
        "context_files": [{"path": str(path), "name": path.name, "included": True} for path, _ in files.values()],
    }), encoding="utf-8")
    try:
        yield fields["patch_artifact"], files
    finally:
        chat_live_log.reset_chat_live_log_state()
        media_handles.reset_digest_memo()


def _rows(caller=STDIO_OWNER) -> dict[str, dict]:
    return {row["reference"]: row for row in _call(INDEX, caller=caller)["result"]["artifacts"]}


def _fetched(handle: str, caller=STDIO_OWNER) -> bytes:
    reply = _call(GET, {"handle": handle}, caller=caller)
    assert "result" in reply, reply
    return base64.b64decode(reply["result"]["data"])


def test_a_driving_device_opens_the_diff_and_the_context_files_by_handle(written):
    diff_path, files = written
    console = _device(TIER_CONSOLE)
    rows = _rows(console)
    diff = rows[diff_path]
    assert (diff["kind"], diff["media_type"]) == ("diff", "text/x-diff")
    assert _fetched(diff["handle"], console) == _DIFF.encode()
    for key, media_type in (("soul", "text/markdown"), ("agents", "text/markdown"), ("skills", "application/json")):
        path, data = files[key]
        row = rows[str(path)]
        assert (row["kind"], row["media_type"], row["handle"]) == ("context_file", media_type, _handle(data))
        assert _fetched(row["handle"], console) == data


def test_config_yaml_and_the_memory_files_are_never_offered_or_served(written):
    _, files = written
    rows = _rows()
    for key in ("config", "memory"):
        path, data = files[key]
        assert str(path) not in rows
        refused = _call(GET, {"handle": _handle(data)})
        assert refused["error"]["data"]["reason"] == media_handles.REASON_UNKNOWN_HANDLE, refused


def test_a_path_or_a_guessed_handle_is_refused(written):
    diff_path, files = written
    for raw in (diff_path, str(files["config"][0]), "../config.yaml"):
        refused = _call(GET, {"handle": raw})
        assert refused["error"]["data"]["reason"] == media_handles.REASON_HANDLE_INVALID, refused
    guessed = _call(GET, {"handle": "sha256:" + "0" * 64})
    assert guessed["error"]["data"]["reason"] == media_handles.REASON_UNKNOWN_HANDLE


def test_a_view_only_device_is_refused_as_it_is_for_the_chat_itself(written):
    diff_path, _ = written
    handle = _rows()[diff_path]["handle"]
    for method, params in ((INDEX, {}), (GET, {"handle": handle})):
        reply = _call(method, params, caller=_device(TIER_READ))
        assert reply["error"]["data"] == {"reason": REASON_SCOPE_DENIED, "tier": TIER_CONSOLE,
                                          "caller": CALLER_DEVICE}


def test_the_peer_keyhole_never_serves_an_agent_written_file(written):
    diff_path, files = written
    peer = RpcCaller(kind=CALLER_PEER, connection_key="c2", transport=TRANSPORT_GATEWAY,
                     peer_install_id="inst_far_away")
    for data in (_DIFF.encode(), files["soul"][1]):
        reply = _call("peer.media.get", {"handle": _handle(data)}, caller=peer)
        assert reply["error"]["data"]["reason"] == media_handles.REASON_UNKNOWN_HANDLE, reply


def test_a_stray_file_beside_the_diffs_is_not_offered(written):
    stray = paths.patch_diffs_dir() / "notes.txt"
    stray.write_bytes(b"not a diff the trace names\n")
    assert str(stray) not in _rows()
