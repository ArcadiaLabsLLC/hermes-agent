"""A SOUL.md or AGENTS.md another device opened by handle is saved back through this engine.

Row ``RT-FU-A-CONTEXT-FILE-OPENED-FROM-ANOTHER-DEVICE-IS-SAVED-BACK-THROUGH-THIS-ENGINE-BY-HANDLE``.
A prompt-context frame (the persisted row ``load_latest_prompt_observability_contexts`` reads) lists
the context files a turn loaded, ``runtime.media.index`` hands their handles out, and
``runtime.media.context_file.write`` is called through the real dispatcher with the caller the
transport would stamp. Every test runs in the ``tests/agent_runtime`` conftest's isolated store root.

Killing mutations (each red seen 2026-11-22):

* ``serve_rpc.media._runtime_media_context_file_write``: resolve against a scope built once and
  cached, and the stale-handle test saves over the newer file (the save test's second save is
  refused too);
* the same verb: drop its ``agent_file_handles.context_file_writable`` check (the predicate the
  index's ``writable`` reads too), and the skills-snapshot test saves the snapshot;
* ``agent_file_handles.SERVED_CONTEXT_FILE_NAMES``: add ``config.yaml``, and the config test's
  handle resolves (refused ``context_file_not_writable``, not ``unknown_handle``);
* the same verb: drop the symlink check, and the symlink test writes through the link;
* its ``@method`` line: state ``computer=COMPUTER_REACH_LOOK``, and the Look computer saves;
  state ``computer=COMPUTER_REACH_CHAT``, and the Run chats computer saves;
* its ``@method`` line: ``tier=TIER_READ``, and the read-tier device saves;
* the same verb: answer ``previous_handle`` as ``handle``, and the save test's next save is stale;
* the same verb: drop the handle grammar check, and the path test is answered ``unknown_handle``.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from agent_runtime import agent_file_handles, chat_live_log, media_handles, paths, serve_rpc
from agent_runtime.call_authorization import (
    CALLER_COMPUTER,
    CALLER_DEVICE,
    REASON_SCOPE_DENIED,
    STDIO_OWNER,
    TIER_CONSOLE,
    TIER_READ,
    TRANSPORT_GATEWAY,
    RpcCaller,
)

INDEX = "runtime.media.index"
WRITE = "runtime.media.context_file.write"


def _device(tier: str) -> RpcCaller:
    return RpcCaller(kind=CALLER_DEVICE, connection_key="c1", transport=TRANSPORT_GATEWAY,
                     device_id="dev_phone", device_tier=tier)


def _computer(grant: str) -> RpcCaller:
    return RpcCaller(kind=CALLER_COMPUTER, connection_key="c3", transport=TRANSPORT_GATEWAY,
                     computer_id="cmp-1", computer_grant=grant)


def _call(method: str, params: dict | None = None, *, caller=STDIO_OWNER) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "w1", "method": method, "params": params or {}},
                                    serve_rpc.RpcContext(caller=caller, transport=TRANSPORT_GATEWAY))


def _handle(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture
def loaded(tmp_path):
    """One turn's context files, listed in a prompt-context frame where the runtime writes it."""

    chat_live_log.reset_chat_live_log_state()
    media_handles.reset_digest_memo()
    profile = tmp_path / "profile"
    workspace = tmp_path / "workspace"
    profile.mkdir()
    workspace.mkdir()
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_bytes(b"# not a context file\n")
    files = {
        "soul": (profile / "SOUL.md", b"# Soul\nbe kind\n"),
        "agents": (workspace / "AGENTS.md", b"# Rules\nrun the tests\n"),
        "skills": (profile / ".skills_prompt_snapshot.json", b'{"skills": ["triage"]}'),
        "config": (profile / "config.yaml", b"model:\n  api_key: sk-secret-never-served\n"),
    }
    for path, data in files.values():
        path.write_bytes(data)
    linked = tmp_path / "linked" / "SOUL.md"
    linked.parent.mkdir()
    linked.symlink_to(elsewhere)
    listed = [path for path, _ in files.values()] + [linked]
    frames = paths.prompt_observability_dir()
    frames.mkdir(parents=True, exist_ok=True)
    (frames / "ctx_one.json").write_text(json.dumps({
        "context_id": "ctx_one",
        "context_files": [{"path": str(path), "name": path.name, "included": True} for path in listed],
    }), encoding="utf-8")
    try:
        yield files, linked, elsewhere
    finally:
        chat_live_log.reset_chat_live_log_state()
        media_handles.reset_digest_memo()


def _save(handle: str, text: str, caller=None) -> dict:
    return _call(WRITE, {"handle": handle, "text": text}, caller=caller or _device(TIER_CONSOLE))


def _reason(reply: dict) -> str:
    assert "error" in reply, reply
    return reply["error"]["data"]["reason"]


def test_a_console_device_saves_soul_by_handle_and_gets_the_new_handle(loaded):
    files, _, _ = loaded
    path, data = files["soul"]
    reply = _save(_handle(data), "# Soul\nbe kinder\n")
    assert "result" in reply, reply
    assert path.read_bytes() == b"# Soul\nbe kinder\n"
    assert reply["result"]["previous_handle"] == _handle(data)
    assert reply["result"]["handle"] == _handle(b"# Soul\nbe kinder\n")
    # The handle the save answered is the one a fresh index serves, so the next save is not stale.
    rows = {row["reference"]: row for row in _call(INDEX)["result"]["artifacts"]}
    assert rows[str(path)]["handle"] == reply["result"]["handle"]
    again = _save(reply["result"]["handle"], "# Soul\nbe kindest\n")
    assert "result" in again, again
    assert path.read_bytes() == b"# Soul\nbe kindest\n"


def test_a_stale_handle_is_refused_and_the_newer_file_is_kept(loaded):
    files, _, _ = loaded
    path, data = files["agents"]
    stale = _handle(data)
    assert "result" in _save(stale, "# Rules\nfirst edit\n")
    assert _reason(_save(stale, "# Rules\nsecond device, old copy\n")) == media_handles.REASON_UNKNOWN_HANDLE
    assert path.read_bytes() == b"# Rules\nfirst edit\n"


def test_the_skills_snapshot_is_served_and_never_saved(loaded):
    files, _, _ = loaded
    path, data = files["skills"]
    reply = _save(_handle(data), '{"skills": []}')
    assert _reason(reply) == agent_file_handles.REASON_CONTEXT_FILE_NOT_WRITABLE
    assert path.read_bytes() == data


def test_config_yaml_has_no_handle_to_save_by(loaded):
    files, _, _ = loaded
    path, data = files["config"]
    assert _reason(_save(_handle(data), "model: {}\n")) == media_handles.REASON_UNKNOWN_HANDLE
    assert path.read_bytes() == data


def test_a_symlinked_context_file_is_refused_and_its_target_unchanged(loaded):
    _, linked, elsewhere = loaded
    target = elsewhere.read_bytes()
    reply = _save(_handle(target), "# written through the link\n")
    assert _reason(reply) == agent_file_handles.REASON_CONTEXT_FILE_IS_SYMLINK
    assert elsewhere.read_bytes() == target and linked.is_symlink()


@pytest.mark.parametrize("grant", ["look", "chat"])
def test_a_look_or_run_chats_computer_is_refused(loaded, grant):
    files, _, _ = loaded
    path, data = files["soul"]
    reply = _save(_handle(data), "# from a computer\n", caller=_computer(grant))
    assert _reason(reply) == REASON_SCOPE_DENIED
    assert path.read_bytes() == data


def test_a_computer_on_the_phones_own_account_saves_as_a_console_device(loaded):
    files, _, _ = loaded
    path, data = files["soul"]
    reply = _save(_handle(data), "# from my own computer\n", caller=_computer("account"))
    assert "result" in reply, reply
    assert path.read_bytes() == b"# from my own computer\n"


def test_a_read_tier_device_is_refused(loaded):
    files, _, _ = loaded
    path, data = files["soul"]
    reply = _save(_handle(data), "# from a viewer\n", caller=_device(TIER_READ))
    assert reply["error"]["data"] == {"reason": REASON_SCOPE_DENIED, "tier": TIER_CONSOLE, "caller": CALLER_DEVICE}
    assert path.read_bytes() == data


def test_a_path_is_never_a_handle(loaded):
    files, _, _ = loaded
    path, data = files["soul"]
    assert _reason(_save(str(path), "# by path\n")) == media_handles.REASON_HANDLE_INVALID
    assert path.read_bytes() == data
