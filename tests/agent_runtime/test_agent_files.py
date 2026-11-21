"""An agent's files, served by its engine as one confined tree (``runtime.agent.files.*``).

Eternia row ``MC-PHONE-FILES-AN-AGENTS-FILES-ARE-SERVED-BY-ITS-ENGINE-AS-ONE-TREE``. Every call
goes through ``serve_rpc.handle_request`` with a caller the transport would mint, so the tier, the
allowlists and the reader are the real ones. The reverse lane's own end-to-end read (a computer
reading a phone agent's tree over the lane the phone dialled) is in ``test_reverse_lane.py``.

Killing mutations (each recorded red, named at its test):

* ``agent_tree.agent_roots``: enumerate every slot of the workspace, not the assigned ones;
* ``agent_tree._split``: take the first segment as a folder (``os.path.join(root_parent, first)``)
  instead of looking it up among the enumerated roots;
* ``agent_tree._admissible``: drop the engine-home check;
* ``reader.read``: drop the size check;
* ``call_authorization.COMPUTER_LOOK_METHOD_ALLOWLIST``: leave the three verbs out.
"""

from __future__ import annotations

import os

import pytest
from hermes_time import now

from agent_runtime import call_authorization as ca
from agent_runtime import paths, serve_rpc
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_slots import set_instance_slots
from agent_runtime.serve_rpc.protocol import RpcContext
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import bind, declare

T0 = "2026-11-21T10:00:00+00:00"
T1 = "2026-11-21T11:00:00+00:00"
INSTANCE = "personainst_files"
VERBS = ("runtime.agent.files.tree", "runtime.agent.files.read", "runtime.agent.files.grep")


def _agent(tmp_path, assigned: dict[str, str], unassigned: dict[str, str] | None = None) -> str:
    """A workspace whose slots are bound to ``folder`` names under tmp_path; ``assigned`` go to the agent."""

    every = {**assigned, **(unassigned or {})}
    workspace = WorkspaceStore().create(name="Files").id
    declare(workspace, [{"name": name, "repo": {"clone_url": f"https://example.com/{name}.git"},
                         "context": {"files": []}} for name in every], issued_at=T0, machine="m")
    for name, folder in every.items():
        bind(workspace, name, folder, issued_at=T0)
    PersonaInstanceStore()._write(PersonaInstance(
        id=INSTANCE, persona_id="dev", role="dev", display_name="files", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, workspace_id=workspace,
        updated_at=now()))
    set_instance_slots(INSTANCE, list(assigned), issued_at=T1)
    return workspace


def _folder(tmp_path, name: str, files: dict[str, bytes | str]) -> str:
    root = tmp_path / name
    root.mkdir()
    for relative, body in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            target.write_bytes(body)
        else:
            target.write_text(body, encoding="utf-8")
    return str(root)


def _call(method: str, params: dict, caller=ca.LOCAL_CONSOLE) -> dict:
    frame = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "t", "method": method, "params": {"persona_instance_id": INSTANCE, **params}},
        context=RpcContext(caller=caller))
    return frame


def _params(verb: str) -> dict:
    return {"runtime.agent.files.tree": {"path": "app"}, "runtime.agent.files.read": {"path": "app/README.md"},
            "runtime.agent.files.grep": {"pattern": "hello"}}[verb]


def _reason(frame: dict) -> str | None:
    return ((frame.get("error") or {}).get("data") or {}).get("reason")


@pytest.fixture
def two_roots(tmp_path):
    app = _folder(tmp_path, "app", {"README.md": "hello app\n", "src/main.dart": "void main() {} // hello\n",
                                    ".git/config": "secret"})
    docs = _folder(tmp_path, "docs", {"guide.md": "nothing\nhello docs\n"})
    _agent(tmp_path, {"app": app, "docs": docs})
    return tmp_path


def test_the_tree_lists_the_agents_roots_as_folders_and_reads_through_them(two_roots):
    top = _call("runtime.agent.files.tree", {"depth": 1})["result"]
    assert top["entries"] == [{"path": "app", "kind": "dir"}, {"path": "docs", "kind": "dir"}]
    deep = _call("runtime.agent.files.tree", {"path": "app"})["result"]
    assert deep["path"] == "app"
    assert [e["path"] for e in deep["entries"]] == ["app/README.md", "app/src", "app/src/main.dart"]
    read = _call("runtime.agent.files.read", {"path": "app/src/main.dart"})["result"]
    assert read["path"] == "app/src/main.dart" and "hello" in read["content"]
    found = _call("runtime.agent.files.grep", {"pattern": "hello"})["result"]
    assert [(m["path"], m["line"]) for m in found["matches"]] == [
        ("app/README.md", 1), ("app/src/main.dart", 1), ("docs/guide.md", 2)]


def test_only_the_agents_own_roots_are_listed_or_read(tmp_path):
    """MUTATION (``agent_tree.agent_roots``): enumerate every slot of the workspace instead of the
    agent's assigned ones, and ``other`` is listed and read."""

    mine = _folder(tmp_path, "mine", {"a.txt": "a"})
    other = _folder(tmp_path, "other", {"b.txt": "b"})
    _agent(tmp_path, {"mine": mine}, {"other": other})
    assert [e["path"] for e in _call("runtime.agent.files.tree", {"depth": 1})["result"]["entries"]] == ["mine"]
    assert _reason(_call("runtime.agent.files.read", {"path": "other/b.txt"})) == "not_found"


@pytest.mark.parametrize("path, reason", [
    ("/etc/passwd", "invalid_path"),
    ("app/../docs/guide.md", "invalid_path"),
    ("app\\README.md", "invalid_path"),
    ("C:/Windows/win.ini", "invalid_path"),
    ("app/.git/config", "ignored"),
    ("app", "not_a_file"),
])
def test_a_caller_never_names_a_folder_of_its_own(two_roots, path, reason):
    assert _reason(_call("runtime.agent.files.read", {"path": path})) == reason


def test_a_first_segment_that_is_no_enumerated_root_is_not_found(two_roots):
    """MUTATION (``agent_tree._split``): resolve the first segment as a folder beside the roots
    (``os.path.join(os.path.dirname(any_root), first)``) and ``elsewhere/secret.txt`` is read."""

    (two_roots / "elsewhere").mkdir()
    (two_roots / "elsewhere" / "secret.txt").write_text("secret", encoding="utf-8")
    frame = _call("runtime.agent.files.read", {"path": "elsewhere/secret.txt"})
    assert _reason(frame) == "not_found"
    assert "secret" not in str(frame)


def test_a_symlink_out_of_a_root_is_listed_as_a_link_and_never_read(two_roots):
    outside = two_roots / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    os.symlink(outside, two_roots / "app" / "escape.txt")
    entries = _call("runtime.agent.files.tree", {"path": "app", "depth": 1})["result"]["entries"]
    assert {"path": "app/escape.txt", "kind": "link"} in entries
    assert _reason(_call("runtime.agent.files.read", {"path": "app/escape.txt"})) == "outside_root"


def test_a_read_over_five_mib_is_refused(tmp_path):
    """MUTATION (``reader.read``): drop the size check, and the 5 MiB + 1 file is answered."""

    big = _folder(tmp_path, "big", {"huge.txt": "x" * (5 * 1024 * 1024 + 1), "small.txt": "ok"})
    _agent(tmp_path, {"big": big})
    assert _reason(_call("runtime.agent.files.read", {"path": "big/huge.txt"})) == "too_large"
    assert _call("runtime.agent.files.read", {"path": "big/small.txt"})["result"]["content"] == "ok"


def test_a_root_over_the_engines_home_is_never_served(tmp_path):
    """No whole-disk browse: a slot bound at a folder holding the engine's home is not a root.

    MUTATION (``agent_tree._admissible``): drop the engine-home check, and ``over`` is listed."""

    from hermes_constants import get_hermes_home

    over = str(get_hermes_home().resolve().parent)
    mine = _folder(tmp_path, "mine", {"a.txt": "a"})
    _agent(tmp_path, {"over": over, "mine": mine})
    assert [e["path"] for e in _call("runtime.agent.files.tree", {"depth": 1})["result"]["entries"]] == ["mine"]
    assert _reason(_call("runtime.agent.files.tree", {"path": "over"})) == "not_found"


def test_an_unknown_agent_is_refused(two_roots):
    frame = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "t", "method": "runtime.agent.files.tree",
         "params": {"persona_instance_id": "personainst_nobody"}}, context=RpcContext(caller=ca.LOCAL_CONSOLE))
    assert _reason(frame) == "instance_not_found"


# ── who may call them ─────────────────────────────────────────────────────────


def _computer(grant: str | None) -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_COMPUTER, connection_key="lane-1", transport="gateway",
                        computer_id="computer-1", computer_grant=grant)


@pytest.mark.parametrize("verb", VERBS)
def test_a_computer_the_phone_granted_look_reaches_the_verbs(two_roots, verb):
    """MUTATION (``COMPUTER_LOOK_METHOD_ALLOWLIST``): leave the verbs out, and look is refused."""

    for grant in (ca.COMPUTER_GRANT_LOOK, ca.COMPUTER_GRANT_CHAT):
        assert "result" in _call(verb, _params(verb), caller=_computer(grant)), grant


@pytest.mark.parametrize("verb", VERBS)
def test_a_computer_with_no_grant_and_a_peer_are_refused(two_roots, verb):
    for caller in (_computer(None), _computer("console"),
                   ca.RpcCaller(kind=ca.CALLER_PEER, connection_key="p", transport="gateway",
                                peer_install_id="install-2")):
        assert _reason(_call(verb, _params(verb), caller=caller)) == ca.REASON_SCOPE_DENIED, caller.kind


@pytest.mark.parametrize("verb", VERBS)
def test_the_verbs_are_read_tier_so_a_viewer_device_driving_the_computer_reaches_them(two_roots, verb):
    assert serve_rpc.registry.method_tier(verb) == ca.TIER_READ
    viewer = ca.RpcCaller(kind=ca.CALLER_DEVICE, connection_key="d", transport="gateway",
                          device_id="phone-1", device_tier=ca.TIER_READ, device_kind=ca.DEVICE_KIND_DEVICE)
    assert "result" in _call(verb, _params(verb), caller=viewer)
