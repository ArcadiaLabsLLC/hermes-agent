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
* ``call_authorization.COMPUTER_LOOK_METHOD_ALLOWLIST``: leave the three verbs out;
* ``agent_files``: a verb's tier back to ``TIER_READ`` (a view-only device reads the project);
* ``reader.read_regular_file`` / ``reader._open_flags``: each guard of the one opener (O_NOFOLLOW,
  O_NONBLOCK, the Windows fallback's lstat refusal and inode pin), named at its test below.
"""

from __future__ import annotations

import os
import threading
import time

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


def test_a_glob_and_a_wildcard_reach_the_reader_across_every_root(two_roots):
    """MUTATION (``agent_files``): drop ``glob=_glob(p)`` from the grep handler, and docs is searched."""

    found = _call("runtime.agent.files.grep", {"pattern": "hello *", "wildcard": True, "glob": "*.md"})["result"]
    assert found["glob"] == "*.md" and found["wildcard"] is True
    assert [(m["path"], m["line"]) for m in found["matches"]] == [("app/README.md", 1), ("docs/guide.md", 2)]
    listed = _call("runtime.agent.files.tree", {"glob": "*.dart"})["result"]
    assert [e["path"] for e in listed["entries"]] == ["app/src/main.dart"]


@pytest.mark.parametrize("params", [
    {"pattern": "hello", "wildcard": "yes"},
    {"pattern": "hello", "glob": 7},
    {"pattern": "a*" * 17 + "b", "wildcard": True},
    {"pattern": "hello", "glob": "src/*.dart"},
])
def test_a_bad_glob_or_wildcard_is_refused_before_any_file_is_read(two_roots, params):
    assert _reason(_call("runtime.agent.files.grep", params)) == "bad_argument"


def test_a_search_past_its_deadline_is_refused_never_answered_in_part(two_roots, monkeypatch):
    """One deadline covers the whole call, every root included, and is asked between entries and
    lines: a search past it is refused ``search_timeout`` at once, never left running or answered
    with the files it reached. (The worst admitted wildcard finishing well inside the real
    deadline is the spec case ``grep_wildcard_pathological_pattern_finishes_within_the_deadline``;
    one past ``max_wildcards`` is refused above.)

    MUTATION (``patterns.Deadline.check``): never raise, and the grep is answered."""

    from agent_runtime.project_files import agent_tree, patterns

    monkeypatch.setattr(agent_tree, "Deadline", lambda: patterns.Deadline(0.0))
    started = time.monotonic()
    grep = _call("runtime.agent.files.grep", {"pattern": "a*" * 16 + "b", "wildcard": True})
    tree = _call("runtime.agent.files.tree", {"glob": "*.md"})
    took = time.monotonic() - started
    assert _reason(grep) == "search_timeout", grep
    assert _reason(tree) == "search_timeout", tree
    assert took < 2.0, f"refused after {took:.2f} s"


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


def _device(tier: str) -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_DEVICE, connection_key="d", transport="gateway",
                        device_id="phone-1", device_tier=tier, device_kind=ca.DEVICE_KIND_DEVICE)


@pytest.mark.parametrize("verb", VERBS)
def test_a_view_only_device_is_refused_the_files_as_it_is_the_chats(two_roots, verb):
    """MUTATION (``agent_files``: a verb's tier back to ``TIER_READ``): the viewer reads the project.

    Row ``RT-FU-A-VIEW-ONLY-DEVICE-CANNOT-READ-AN-AGENTS-PROJECT-FILES``: a device paired ``read`` is
    refused ``runtime.persona.chat.history``, so it is refused the files the chats are about.
    """

    assert serve_rpc.registry.method_tier(verb) == ca.TIER_CONSOLE
    assert _reason(_call(verb, _params(verb), caller=_device(ca.TIER_READ))) == ca.REASON_SCOPE_DENIED


@pytest.mark.parametrize("verb", VERBS)
def test_a_console_device_driving_the_computer_still_reads_the_files(two_roots, verb):
    """MUTATION (``call_authorization.LOCAL_CONSOLE_METHODS``: add the verbs, owner-only): the default phone is refused."""

    assert "result" in _call(verb, _params(verb), caller=_device(ca.TIER_CONSOLE))


# ---- The one regular-file opener (row RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY) ----
#
# The walk saw a regular file; ``reader.read_regular_file`` opens it a moment later with O_NOFOLLOW and
# O_NONBLOCK and keeps it only when fstat still says regular. Each case swaps the file between the walk and
# the open (``_swap_after_walk``) and greps through the RPC, which runs on desktops, Windows included.


def _swap_after_walk(monkeypatch, swap) -> None:
    from agent_runtime.project_files import reader

    walk = reader._walk_project_folder

    def walk_then_swap(*args, **kwargs):
        walk(*args, **kwargs)
        swap()

    monkeypatch.setattr(reader, "_walk_project_folder", walk_then_swap)


def _replace_with_link(path, target) -> None:
    os.remove(path)
    os.symlink(target, path)


@pytest.fixture
def swap_root(tmp_path):
    app = _folder(tmp_path, "app", {"a.txt": "nothing\n", "b.txt": "hello b\n"})
    (tmp_path / "outside.txt").write_text("hello outside\n", encoding="utf-8")
    _agent(tmp_path, {"app": app})
    return tmp_path


def _grepped(pattern: str = "hello") -> list[tuple[str, int, str]]:
    found = _call("runtime.agent.files.grep", {"pattern": pattern})["result"]
    return [(m["path"], m["line"], m["text"]) for m in found["matches"]]


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW is POSIX; the Windows fallback is tested below")
def test_a_file_swapped_for_a_link_after_the_walk_is_never_read(swap_root, monkeypatch):
    """MUTATION (``reader._open_flags``): drop O_NOFOLLOW, and the link out of the root is read, red."""

    _swap_after_walk(monkeypatch, lambda: _replace_with_link(swap_root / "app" / "a.txt", swap_root / "outside.txt"))
    assert _grepped() == [("app/b.txt", 1, "hello b")]


def test_without_o_nofollow_a_swapped_link_is_still_never_read(swap_root, monkeypatch):
    """Windows has no O_NOFOLLOW: ``lstat`` refuses the link. MUTATION (``reader.read_regular_file``):
    skip the fallback's lstat refusal and its inode pin, and the link is followed, red."""

    from agent_runtime.project_files import reader

    monkeypatch.setattr(reader, "_NOFOLLOW", 0)
    _swap_after_walk(monkeypatch, lambda: _replace_with_link(swap_root / "app" / "a.txt", swap_root / "outside.txt"))
    assert _grepped() == [("app/b.txt", 1, "hello b")]


def test_without_o_nofollow_a_link_swapped_in_after_lstat_is_never_read(swap_root, monkeypatch):
    """The window between ``lstat`` and the open: the opened file must be the one ``lstat`` saw.
    MUTATION (``reader.read_regular_file``): drop the (st_dev, st_ino) pin, and the link is followed, red."""

    from agent_runtime.project_files import reader

    monkeypatch.setattr(reader, "_NOFOLLOW", 0)
    real_open = os.open
    victim = str(swap_root / "app" / "a.txt")

    def open_after_a_swap(path, flags, *args, **kwargs):
        if path == victim and not os.path.islink(path):
            _replace_with_link(path, swap_root / "outside.txt")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(reader.os, "open", open_after_a_swap)
    assert _grepped() == [("app/b.txt", 1, "hello b")]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs on this platform")
def test_a_file_swapped_for_a_fifo_after_the_walk_never_blocks_the_grep(swap_root, monkeypatch):
    """MUTATION (``reader._open_flags``): drop O_NONBLOCK, and the open waits for a writer that never
    comes, past the deadline, red."""

    fifo = swap_root / "app" / "a.txt"

    def to_fifo():
        os.remove(fifo)
        os.mkfifo(fifo)

    _swap_after_walk(monkeypatch, to_fifo)
    answer: list = []
    grep = threading.Thread(target=lambda: answer.append(_grepped()), daemon=True)
    grep.start()
    grep.join(5.0)
    if grep.is_alive():  # release the blocked open so the thread ends, then fail
        os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
        grep.join(5.0)
        pytest.fail("the grep blocked on a FIFO swapped in after the walk")
    assert answer == [[("app/b.txt", 1, "hello b")]]


def test_the_agent_files_grep_keeps_the_spec_literal_never_a_regex(tmp_path):
    """Regex is a phone ``search_files`` dialect only: over ``runtime.agent.files.grep`` a pattern with
    regex characters is literal text. MUTATION (``reader.grep_matches``): default ``matcher`` to the
    phone's regex matcher, and ``hel+o`` finds "hello", red."""

    app = _folder(tmp_path, "app", {"a.txt": "hello\nliteral hel+o\n"})
    _agent(tmp_path, {"app": app})
    assert _grepped("hel+o") == [("app/a.txt", 2, "literal hel+o")]
