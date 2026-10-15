"""The setup recipe ("image"), Phase B (plan ``build-running-work-2026-10-04.md`` §3.5, row H10).

Derived steps come from the declaration and cannot be deleted, only annotated; the owner adds
``command`` steps; ``ready`` is ``unknown`` whenever any input is unknown, never optimistically
``yes``; the higher ``recipe.revision`` wins — at the local door and in the realm merge.
"""

from __future__ import annotations

import copy
import subprocess

import pytest

from agent_runtime import serve_rpc
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slot_recipe import readiness
from agent_runtime.workspace_slots import declare, load_document, write_document
from agent_runtime.workspace_slots_sync import merge_documents

CLONE_URL = "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git"
ISSUED = "2026-10-05T12:00:00+00:00"
LATER = "2026-10-05T13:00:00+00:00"
REMOVED = "2026-10-05T14:00:00+00:00"


def call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _decl(name="launcher", **toolchain) -> dict:
    base = {"kind": "flutter", "tools": [{"name": "flutter", "min_version": "3.41"}, {"name": "dart"}],
            "env_keys": [{"key": "FLUTTER_ROOT", "required": True}, {"key": "PUB_CACHE", "required": False}],
            "dotenv": {"path": ".env", "keys": [{"key": "ETERNIA_API_BASE", "required": True},
                                               {"key": "OPTIONAL_FLAG", "required": False}]}}
    base.update(toolchain)
    return {"name": name, "repo": {"clone_url": CLONE_URL, "default_branch": "main"}, "toolchain": base}


@pytest.fixture
def workspace():
    machine_roots_cache_clear()
    workspace_id = WorkspaceStore().create(name="Recipe").id
    reply = call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": [_decl(), _decl("backend")],
                                                      "issued_at": ISSUED})
    assert "result" in reply, reply
    return workspace_id


def _set(workspace, steps, revision, slot="launcher", issued_at=LATER) -> dict:
    return call("runtime.workspace.recipe.set", {"workspace_id": workspace, "slot": slot, "steps": steps,
                                                  "revision": revision, "issued_at": issued_at})


def _show(workspace) -> dict:
    return call("runtime.workspace.recipe.show", {"workspace_id": workspace})["result"]["slots"]


def _ids(checklist) -> list[str]:
    return [step["id"] for step in checklist["steps"]]


DERIVED = ["clone", "tool:flutter", "tool:dart", "env_key:FLUTTER_ROOT", "env_key:PUB_CACHE", "dotenv"]


# ── derived steps cannot be deleted, only annotated ──────────────────────────


def test_derived_steps_are_materialised_and_an_empty_owner_list_deletes_none(workspace):
    assert _ids(_show(workspace)["launcher"]) == DERIVED
    reply = _set(workspace, [], 0)["result"]
    assert reply["revision"] == 1
    assert _ids(_show(workspace)["launcher"]) == DERIVED
    # Nothing derived is ever stored: the record holds only the owner's part.
    assert load_document(workspace)["slots"]["launcher"]["recipe"]["steps"] == []


def test_a_derived_step_is_annotated_never_edited(workspace):
    edited = _set(workspace, [{"id": "tool:flutter", "min_version": "1.0"}], 0)
    assert edited["error"]["data"]["reason"] == "derived_step_immutable"
    rekinded = _set(workspace, [{"id": "tool:flutter", "kind": "env_key"}], 0)
    assert rekinded["error"]["data"]["reason"] == "derived_step_immutable"
    assert _set(workspace, [{"id": "tool:rust"}], 0)["error"]["data"]["reason"] == "unknown_step"
    assert load_document(workspace)["slots"]["launcher"]["recipe"]["revision"] == 0  # nothing landed
    # Positive control: the same step, annotated, lands and shows.
    assert "result" in _set(workspace, [{"id": "tool:flutter", "hint": "Use the 3.41 SDK", "url": "https://docs.flutter.dev"}], 0)
    flutter = next(s for s in _show(workspace)["launcher"]["steps"] if s["id"] == "tool:flutter")
    assert flutter["hint"] == "Use the 3.41 SDK" and flutter["url"] == "https://docs.flutter.dev"
    assert flutter["min_version"] == "3.41"  # the declaration's value, untouched


def test_owner_commands_follow_the_derived_steps_and_never_run_on_their_own(workspace):
    steps = [{"id": "pub_get", "kind": "command", "argv": ["flutter", "pub", "get"]},
             {"id": "codegen", "kind": "command", "argv": ["dart", "run", "build_runner", "build"], "run": "never_auto",
              "cwd_slot": "backend"}]
    assert "result" in _set(workspace, steps, 0)
    checklist = _show(workspace)["launcher"]
    assert _ids(checklist) == DERIVED + ["pub_get", "codegen"]
    by_id = {s["id"]: s for s in checklist["steps"]}
    assert by_id["pub_get"]["run"] == "on_setup_click" and by_id["pub_get"]["state"] == "offered"
    assert by_id["codegen"]["state"] == "manual" and by_id["codegen"]["cwd_slot"] == "backend"


@pytest.mark.parametrize(("step", "reason"), [
    ({"id": "clone", "kind": "command", "argv": ["x"]}, "invalid_step"),
    ({"id": "a", "kind": "command", "argv": []}, "invalid_step"),
    ({"id": "a", "kind": "command", "argv": ["x"], "run": "on_clone"}, "invalid_step"),
    ({"id": "a", "kind": "command", "argv": ["x"], "cwd_slot": "nowhere"}, "invalid_step"),
    ({"id": "a", "kind": "locate"}, "invalid_step"),
])
def test_a_bad_owner_step_is_refused_typed(workspace, step, reason):
    assert _set(workspace, [step], 0)["error"]["data"]["reason"] == reason


def test_a_duplicate_step_id_is_refused(workspace):
    twice = [{"id": "a", "kind": "command", "argv": ["x"]}, {"id": "a", "kind": "command", "argv": ["y"]}]
    assert _set(workspace, twice, 0)["error"]["data"]["reason"] == "duplicate_step_id"


@pytest.mark.parametrize("token", [
    "https://ghp-not-a-real-token@github.com/x/y.git",
    "https://user:not-a-real-password@example.com/r.git",
    "--header=Authorization: Bearer not-a-real-bearer-value",
    "API_KEY=not-a-real-key-value",
])
def test_no_credential_enters_a_recipe(workspace, token):
    assert _set(workspace, [{"id": "a", "kind": "command", "argv": ["git", token]}], 0)["error"]["data"]["reason"] == \
        "credential_in_step"
    # Positive control: the same step with a credential-free token lands.
    assert "result" in _set(workspace, [{"id": "a", "kind": "command", "argv": ["git", "https://github.com/x/y.git"]}], 0)


@pytest.mark.parametrize("step", [
    {"id": "a", "kind": "command", "argv": ["flutter", "pub", "get"], "label": "token=not-a-real-token-value-0123"},
    {"id": "env_key:FLUTTER_ROOT", "hint": "Authorization: Bearer not-a-real-bearer-value"},
])
def test_no_credential_rides_a_label_or_a_hint(workspace, step):
    assert _set(workspace, [step], 0)["error"]["data"]["reason"] == "credential_in_step"
    # Positive control: the same step, its prose credential-free, lands (an env_key id is an id, not an assignment).
    prose = {**step, **({"label": "Fetch packages"} if "label" in step else {"hint": "Set it to your SDK root"})}
    assert "result" in _set(workspace, [prose], 0)


# ── revision wins ────────────────────────────────────────────────────────────


def test_a_stale_editor_loses_to_the_higher_revision(workspace):
    assert _set(workspace, [{"id": "a", "kind": "command", "argv": ["x"]}], 0)["result"]["revision"] == 1
    stale = _set(workspace, [], 0)
    assert stale["error"]["code"] == serve_rpc.ERR_CONFLICT and stale["error"]["data"]["reason"] == "stale_revision"
    assert _ids(_show(workspace)["launcher"])[-1] == "a"


def test_a_changed_declaration_advances_the_revision_so_an_open_editor_is_refused(workspace):
    _set(workspace, [], 0)
    changed = _decl(env_keys=[{"key": "FLUTTER_ROOT", "required": True}])
    call("runtime.workspace.slots.declare", {"workspace_id": workspace, "slots": [changed, _decl("backend")],
                                             "issued_at": LATER})
    slots = load_document(workspace)["slots"]
    assert slots["launcher"]["recipe"]["revision"] == 2 and slots["backend"]["recipe"]["revision"] == 0
    assert _set(workspace, [], 1, issued_at=LATER)["error"]["data"]["reason"] == "stale_revision"


def test_a_peer_removal_beats_an_older_recipe_edit_in_the_realm_merge(workspace):
    """A removal advances the revision like an edit, so the NEWER of the two decisions wins.

    Without the advance the peer's tombstone (revision 0) would lose to this machine's older
    recipe edit (revision 1) and the merge would resurrect a slot the workspace removed.
    """

    peer_before = copy.deepcopy(load_document(workspace))
    _set(workspace, [{"id": "a", "kind": "command", "argv": ["x"]}], 0)
    mine = load_document(workspace)
    write_document(workspace, peer_before)
    declare(workspace, [_decl("backend")], issued_at=REMOVED, machine="mach_peer")
    theirs = load_document(workspace)
    assert theirs["slots"]["launcher"]["recipe"]["revision"] == mine["slots"]["launcher"]["recipe"]["revision"] == 1
    assert merge_documents(mine, theirs)["slots"]["launcher"]["removed_at"] == REMOVED


# ── readiness: the truth table ───────────────────────────────────────────────


def _slot_body():
    from agent_runtime.workspace_slots import normalize_declaration

    return normalize_declaration(_decl())[1]


def _row(**over) -> dict:
    row = {"bound": True, "checkout": "matches",
           "tools": {"flutter": {"status": "set", "version": "3.41.2"}, "dart": {"status": "set", "version": "3.11.1"}},
           "env_keys": {"FLUTTER_ROOT": "set", "PUB_CACHE": "set"},
           "dotenv": {"present": True, "keys": {"ETERNIA_API_BASE": "set", "OPTIONAL_FLAG": "set"}}}
    row.update(over)
    return row


@pytest.mark.parametrize(("row", "ready", "checklist"), [
    (_row(), "yes", "ready"),
    (None, "unknown", "unknown"),
    ({"bound": False, "status": "not_cloned"}, "no", "not_cloned"),
    ({"bound": True, "status": "path_missing"}, "no", "path_missing"),
    (_row(checkout="remote_mismatch"), "no", "remote_mismatch"),
    (_row(checkout="not_a_repo"), "no", "needs_setup"),
    (_row(checkout="unknown"), "unknown", "unknown"),
    (_row(tools={"flutter": {"status": "missing", "version": None}, "dart": {"status": "set", "version": "3"}}), "no", "needs_setup"),
    (_row(tools={"flutter": {"status": "set", "version": "3.40.9"}, "dart": {"status": "set", "version": "3"}}), "no", "needs_setup"),
    (_row(tools={"flutter": {"status": "set", "version": None}, "dart": {"status": "set", "version": "3"}}), "unknown", "unknown"),
    (_row(tools={"flutter": {"status": "unknown", "version": None}, "dart": {"status": "set", "version": "3"}}), "unknown", "unknown"),
    (_row(tools={"flutter": {"status": "set", "version": "3.41.2"}}), "unknown", "unknown"),  # dart never probed
    (_row(env_keys={"FLUTTER_ROOT": "missing", "PUB_CACHE": "set"}), "no", "needs_setup"),
    (_row(env_keys={"FLUTTER_ROOT": "set", "PUB_CACHE": "missing"}), "yes", "ready"),  # optional ⇒ a note
    (_row(env_keys={"FLUTTER_ROOT": "set"}), "unknown", "unknown"),  # PUB_CACHE absent from the report
    (_row(dotenv={"present": False, "keys": {"ETERNIA_API_BASE": "missing", "OPTIONAL_FLAG": "missing"}}), "no", "needs_setup"),
    (_row(dotenv={"present": True, "keys": {"ETERNIA_API_BASE": "unknown", "OPTIONAL_FLAG": "unknown"}}), "unknown", "unknown"),
    (_row(dotenv=None), "unknown", "unknown"),
    # The unknown arm outranks a definite miss: a missing tool beside an unknown key is unknown.
    (_row(tools={"flutter": {"status": "missing", "version": None}, "dart": {"status": "unknown", "version": None}}),
     "unknown", "unknown"),
])
def test_ready_truth_table(row, ready, checklist):
    answer = readiness("launcher", _slot_body(), row)
    assert (answer["ready"], answer["checklist"]) == (ready, checklist)
    if ready == "yes":
        assert answer["unknown"] == [] and answer["blocking"] == []


def test_an_optional_miss_is_a_note_and_a_required_miss_is_blocking():
    answer = readiness("launcher", _slot_body(), _row(env_keys={"FLUTTER_ROOT": "missing", "PUB_CACHE": "missing"}))
    assert answer["blocking"] == ["env_key:FLUTTER_ROOT"] and answer["notes"] == ["env_key:PUB_CACHE"]


def test_a_never_reported_machine_reads_unknown_not_ready(workspace):
    checklist = _show(workspace)["launcher"]
    assert checklist["ready"] == "unknown" and set(checklist["unknown"]) == set(DERIVED)
    assert all(s["why"] == "not_reported" for s in checklist["steps"])


# ── one authority: the probe's status IS the readiness answer ────────────────


def test_the_report_status_is_the_readiness_answer(tmp_path):
    machine_roots_cache_clear()
    workspace_id = WorkspaceStore().create(name="Probe").id
    bare = {"name": "launcher", "repo": {"clone_url": CLONE_URL}}
    call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": [bare], "issued_at": ISSUED})
    repo = tmp_path / "launcher"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://example.com/fork.git"], check=True)
    row = call("runtime.workspace.slot.bind", {"workspace_id": workspace_id, "slot": "launcher", "path": str(repo),
                                               "issued_at": ISSUED})["result"]["report"]
    assert row["checkout"] == "remote_mismatch" and row["status"] == "needs_setup"
    shown = _show(workspace_id)["launcher"]
    assert shown["ready"] == "no" and shown["checklist"] == "remote_mismatch"
    # Positive control: the declared remote makes the same checkout ready.
    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", CLONE_URL], check=True)
    again = call("runtime.workspace.slots.report", {"workspace_id": workspace_id})["result"]["slots"]["launcher"]
    assert again["status"] == "ready" and _show(workspace_id)["launcher"]["ready"] == "yes"
