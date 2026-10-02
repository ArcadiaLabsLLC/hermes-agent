"""`hermes harness level show` — the operator's read of a workspace's level.

``level set`` and ``level clear`` were deleted as argv verbs on 2026-10-02
(owner ruling: the launcher reaches them only as ``runtime.level.set`` /
``runtime.level.clear``, whose cases are ``tests/agent_runtime/test_level_rpc.py``).
What stays is the read, and the contract it holds: the launcher owns the level
document's FORMAT and hermes owns its transport, so ``show --full`` hands back
the stored bytes unchanged — not "a document that parses the same".
"""

from __future__ import annotations

import hashlib
import json

import pytest

from agent_runtime import paths as runtime_paths
from agent_runtime.level_sync import LevelStore
from agent_runtime.store import WorkspaceStore

from tests.agent_runtime._harness_cli import run_harness_in_process

WS = "ws_launcher"


def _document(*, prop_x: float = 1.0) -> str:
    return json.dumps(
        {
            "version": 6,
            "scene": {"id": f"ws-{WS}", "props": [{"id": "a1b2c3d4", "x": prop_x, "y": 2.0}]},
        },
        indent=2,
        sort_keys=True,
    )


def _run(*args: str):
    return run_harness_in_process("level", *args)


def _payload(result):
    return json.loads(result.stdout)


def test_show_full_returns_the_stored_bytes_unchanged(isolate_agent_runtime_root):
    document = _document()
    LevelStore().write(WS, document.encode("utf-8"))

    read_back = _run("show", "--workspace", WS, "--full", "--json")
    assert read_back.returncode == 0
    body = _payload(read_back)

    assert body["present"] is True
    assert body["version"] == 6
    # The property the read is actually about, stated as bytes.
    assert body["document"].encode("utf-8") == document.encode("utf-8")
    assert body["sha256"] == hashlib.sha256(document.encode("utf-8")).hexdigest()


def test_show_on_a_workspace_with_no_level_is_an_honest_empty_not_an_error(
    isolate_agent_runtime_root,
):
    result = _run("show", "--workspace", "ws_never_authored", "--full", "--json")

    assert result.returncode == 0
    body = _payload(result)
    assert body["present"] is False
    assert body["document"] is None
    assert body["version"] is None


def test_show_falls_back_to_the_active_workspace(isolate_agent_runtime_root):
    workspace = WorkspaceStore().create(name="Active")
    WorkspaceStore().set_active(workspace.id)
    LevelStore().write(workspace.id, _document().encode("utf-8"))

    body = _payload(_run("show", "--json"))

    assert body["workspace_id"] == workspace.id
    assert body["present"] is True


def test_show_names_which_root_answered(isolate_agent_runtime_root):
    """A wrong runtime root returns a well-formed EMPTY answer — ``present:
    false`` — indistinguishable from a workspace that genuinely has no level.
    The resolution block is what makes the envelope say which root it read."""

    body = _payload(_run("show", "--workspace", WS, "--json"))

    assert "resolution" in body


def test_a_stored_document_that_stops_reading_is_still_handed_back(
    isolate_agent_runtime_root,
):
    """The repair path. A ``show`` that refused an unreadable stored document
    would leave the operator with no way to see what is in the file that broke
    — so the row stays, ``version`` goes null, and ``--full`` still carries the
    bytes."""

    path = runtime_paths.level_path(WS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{half a document")

    result = _run("show", "--workspace", WS, "--full", "--json")

    assert result.returncode == 0
    body = _payload(result)
    assert body["present"] is True
    assert body["version"] is None
    assert body["document"] == "{half a document"


@pytest.mark.parametrize("verb", ["set", "clear"])
def test_the_write_verbs_are_gone(isolate_agent_runtime_root, verb):
    """The 2026-10-02 deletion, pinned: argparse refuses the verb (exit 2) and
    nothing is written. ``runtime.level.*`` is the only write door."""

    result = _run(verb, "--workspace", WS, "--document", _document(), "--json")

    assert result.returncode == 2
    assert LevelStore().read(WS) is None
