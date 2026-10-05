"""Repo slots, Phase A (plan ``build-running-work-2026-10-04.md`` §3.1–3.4, row H5a).

The workspace declares, the machine fills, the accounting reports set / missing / unknown and
NEVER a value. Every refusal is a typed ``data.reason``; there are no count limits.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.machine_roots import load_machine_roots, machine_roots_cache_clear, write_machine_roots
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import load_document

CLONE_URL = "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git"
ISSUED = "2026-10-04T12:00:00+00:00"
LATER = "2026-10-04T13:00:00+00:00"
SECRET_VALUES = ("C:\\fill\\flutter-root-VALUE-41", "sk-dotenv-secret-VALUE-77", "plain-api-base-VALUE-93")


def call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _slot(name="launcher", **extra) -> dict:
    return {
        "name": name,
        "repo": {"clone_url": CLONE_URL, "default_branch": "main"},
        "toolchain": {
            "kind": "flutter",
            "tools": [{"name": "python_probe"}, {"name": "definitely_absent_tool_zz"}],
            "env_keys": [{"key": "FLUTTER_ROOT", "required": True}, {"key": "PUB_CACHE_SLOT_TEST", "required": False}],
            "dotenv": {"path": ".env", "keys": [{"key": "ETERNIA_API_BASE", "required": True},
                                               {"key": "KEYCLOAK_CLIENT_SECRET", "required": True, "secret": True}]},
        },
        "context": {"role": "launcher / frontend"},
        **extra,
    }


@pytest.fixture
def workspace():
    machine_roots_cache_clear()
    return WorkspaceStore().create(name="Slots").id


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "checkouts" / "launcher"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", CLONE_URL], check=True)
    (repo / ".env").write_text(f"ETERNIA_API_BASE={SECRET_VALUES[2]}\nKEYCLOAK_CLIENT_SECRET={SECRET_VALUES[1]}\n",
                               encoding="utf-8")
    return repo


def _declare(workspace, slots, issued_at=ISSUED) -> dict:
    return call("runtime.workspace.slots.declare", {"workspace_id": workspace, "slots": slots, "issued_at": issued_at})


def test_declare_replaces_the_declared_set_and_tombstones_what_left(workspace):
    assert "result" in _declare(workspace, [_slot("launcher"), _slot("backend")])
    reply = _declare(workspace, [_slot("launcher")], issued_at=LATER)
    assert reply["result"]["tombstoned"] == ["backend"]
    slots = load_document(workspace)["slots"]
    assert slots["backend"]["removed_at"] == LATER and slots["launcher"]["removed_at"] is None
    # context.files defaults to BOTH files (owner correction 2026-10-04).
    assert slots["launcher"]["context"]["files"] == ["CLAUDE.md", "AGENTS.md"]
    # An older declaration cannot undo a newer one.
    stale = _declare(workspace, [_slot("launcher"), _slot("backend")], issued_at=ISSUED)
    assert stale["error"]["data"]["reason"] == "stale_revision"


@pytest.mark.parametrize(
    ("slot", "reason"),
    [(_slot("bad-name"), "invalid_slot_name"), (_slot(repo={"clone_url": "file:///x"}), "invalid_clone_url")],
)
def test_a_bad_declaration_is_refused_typed(workspace, slot, reason):
    reply = _declare(workspace, [slot])
    assert reply["error"]["data"]["reason"] == reason
    assert load_document(workspace)["slots"] == {}


def test_bind_writes_the_machine_root_and_reports(workspace, checkout):
    _declare(workspace, [_slot()])
    reply = call("runtime.workspace.slot.bind", {"workspace_id": workspace, "slot": "launcher", "path": str(checkout),
                                                  "issued_at": ISSUED})["result"]
    assert load_machine_roots(refresh=True).roots["launcher"] == str(checkout)
    assert reply["bound_here"] is True and reply["warnings"] == []
    row = reply["report"]
    assert row["checkout"] == "matches"
    assert row["dotenv"] == {"present": True, "keys": {"ETERNIA_API_BASE": "set", "KEYCLOAK_CLIENT_SECRET": "set"}}
    assert "adopted_existing_root" not in row  # freshly bound, not adopted


def test_a_mismatched_remote_still_binds_with_a_typed_warning(workspace, checkout):
    subprocess.run(["git", "-C", str(checkout), "remote", "set-url", "origin", "https://example.com/fork.git"], check=True)
    _declare(workspace, [_slot()])
    reply = call("runtime.workspace.slot.bind", {"workspace_id": workspace, "slot": "launcher", "path": str(checkout),
                                                  "issued_at": ISSUED})["result"]
    assert reply["warnings"] == ["remote_mismatch"] and reply["report"]["checkout"] == "remote_mismatch"


def test_an_existing_root_is_adopted_and_the_first_report_says_so(workspace, checkout):
    write_machine_roots({"launcher": str(checkout)}, dry_run=False)
    _declare(workspace, [_slot()])
    row = call("runtime.workspace.slots.report", {"workspace_id": workspace})["result"]["slots"]["launcher"]
    assert row["adopted_existing_root"] is True
    again = call("runtime.workspace.slots.report", {"workspace_id": workspace})["result"]["slots"]["launcher"]
    assert "adopted_existing_root" not in again


def test_the_written_document_carries_no_value_and_no_path(workspace, checkout, monkeypatch):
    _declare(workspace, [_slot()])
    call("runtime.workspace.slot.bind", {"workspace_id": workspace, "slot": "launcher", "path": str(checkout), "issued_at": ISSUED})
    reply = call("runtime.workspace.slot.env.set", {
        "workspace_id": workspace, "slot": "launcher", "env": {"FLUTTER_ROOT": SECRET_VALUES[0]},
        "tool_paths": {"python_probe": sys.executable}, "issued_at": ISSUED,
    })["result"]
    row = reply["report"]
    assert row["env_keys"] == {"FLUTTER_ROOT": "set", "PUB_CACHE_SLOT_TEST": "missing"}
    assert row["tools"]["python_probe"]["status"] == "set" and row["tools"]["python_probe"]["version"]
    assert row["tools"]["definitely_absent_tool_zz"] == {"status": "missing", "version": None}
    written = paths.workspace_slots_path(workspace).read_text(encoding="utf-8")
    for value in (*SECRET_VALUES, str(checkout), sys.executable):
        assert value not in written and json.dumps(value)[1:-1] not in written
    # Positive control: the keys themselves ARE in the document — the grep can see text.
    assert "FLUTTER_ROOT" in written and "KEYCLOAK_CLIENT_SECRET" in written


def test_a_secret_key_value_is_refused_in_the_fill(workspace):
    _declare(workspace, [_slot()])
    reply = call("runtime.workspace.slot.env.set", {"workspace_id": workspace, "slot": "launcher",
                                                     "env": {"KEYCLOAK_CLIENT_SECRET": "x"}, "issued_at": ISSUED})
    assert reply["error"]["data"]["reason"] == "secret_in_env"


def test_a_hanging_version_probe_is_unknown_with_evidence(workspace, checkout):
    from agent_runtime.workspace_slots_probe import report

    _declare(workspace, [_slot()])
    write_machine_roots({"launcher": str(checkout)}, dry_run=False)

    def runner(argv, **kwargs):
        if argv[-1] == "--version":
            raise subprocess.TimeoutExpired(argv, 10)
        return subprocess.CompletedProcess(argv, 0, stdout=CLONE_URL + "\n", stderr="")

    from agent_runtime.workspace_slot_env import set_slot_fill

    set_slot_fill(workspace, "launcher", tool_paths={"python_probe": sys.executable})
    row = report(workspace, run=runner)["slots"]["launcher"]
    assert row["tools"]["python_probe"]["status"] == "unknown"
    assert row["status"] == "unknown"
    [entry] = row["unknowns"]
    assert entry["kind"] == "slot_probe_unknown" and "python_probe --version: TimeoutExpired" in entry["evidence"]


def test_an_unbound_slot_names_the_machines_that_bind_it(workspace):
    _declare(workspace, [_slot()])
    document = load_document(workspace)
    document["machines"] = {"mach_far": {"reported_at": ISSUED, "slots": {"launcher": {"bound": True}}},
                            "mach_none": {"reported_at": ISSUED, "slots": {"launcher": {"bound": False}}}}
    from agent_runtime.workspace_slots import write_document

    write_document(workspace, document)
    here = call("runtime.workspace.slots.show", {"workspace_id": workspace})["result"]["here"]["launcher"]
    assert here["bound_here"] is False and here["path"] is None
    [entry] = here["unknowns"]
    assert entry["kind"] == "slot_unbound_here" and "mach_far" in entry["evidence"] and "mach_none" not in entry["evidence"]


def test_no_count_limit_two_hundred_slots_round_trip(workspace):
    slots = [_slot(f"s{i}") for i in range(200)]
    assert "result" in _declare(workspace, slots)
    assert len(load_document(workspace)["slots"]) == 200
    assert len(call("runtime.workspace.slots.show", {"workspace_id": workspace})["result"]["here"]) == 200


def test_declare_is_gated_on_the_realm_publish_right(workspace, monkeypatch):
    from agent_runtime.realm_sync.models import MembershipDecision, RealmMembershipProvider
    from agent_runtime.store import RealmStore

    realm = RealmStore().create(name="Shared realm")
    store = WorkspaceStore()
    gated = store.create(name="In realm", realm_id=realm.id).id
    assert "result" in _declare(gated, [_slot()])  # positive control: the local allow stub
    monkeypatch.setattr(RealmMembershipProvider, "authorize",
                        lambda self, realm, action: MembershipDecision(False, "membership_denied", "no"))
    reply = _declare(gated, [_slot()], issued_at=LATER)
    assert reply["error"]["code"] == serve_rpc.ERR_HANDLER_FAILED
    assert reply["error"]["data"]["reason"] == "realm_publish_denied"


def test_the_machine_fill_file_is_hard_excluded_from_realm_sync():
    from agent_runtime.realm_sync.families import _is_hard_excluded_path
    from agent_runtime.workspace_slot_env import MACHINE_SLOT_ENV_FILENAME

    assert _is_hard_excluded_path(MACHINE_SLOT_ENV_FILENAME)
    assert not _is_hard_excluded_path("store/workspace_slots/ws.json")


def test_the_store_directory_is_in_the_stream_fingerprint(workspace):
    from agent_runtime.stream import _scope_fingerprint

    before = _scope_fingerprint()
    _declare(workspace, [_slot()])
    assert _scope_fingerprint() != before
    assert os.path.isdir(paths.workspace_slots_dir())


def test_show_answers_the_fill_shape_and_never_a_value(workspace):
    _declare(workspace, [_slot()])
    call("runtime.workspace.slot.env.set", {
        "workspace_id": workspace, "slot": "launcher", "env": {"FLUTTER_ROOT": SECRET_VALUES[0]},
        "tool_paths": {"python_probe": sys.executable}, "path_prepend": ["C:/flutter/bin"], "dotenv": ".env",
        "issued_at": ISSUED,
    })
    reply = call("runtime.workspace.slots.show", {"workspace_id": workspace})["result"]
    assert reply["here"]["launcher"]["fill"] == {
        "env_keys": ["FLUTTER_ROOT"], "tool_paths": {"python_probe": sys.executable},
        "path_prepend": ["C:/flutter/bin"], "dotenv": ".env", "venv": None, "bound_at": ISSUED,
    }
    shown = json.dumps(reply)
    assert SECRET_VALUES[0] not in shown and json.dumps(SECRET_VALUES[0])[1:-1] not in shown
    # Positive control: the KEY is shown, so the grep can see the fill at all.
    assert "FLUTTER_ROOT" in shown


def test_show_answers_null_for_a_slot_this_machine_never_filled(workspace):
    _declare(workspace, [_slot()])
    assert call("runtime.workspace.slots.show", {"workspace_id": workspace})["result"]["here"]["launcher"]["fill"] is None


def test_env_keep_changes_one_key_without_clearing_the_rest(workspace):
    from agent_runtime.workspace_slot_env import slot_fill

    _declare(workspace, [_slot()])
    call("runtime.workspace.slot.env.set", {"workspace_id": workspace, "slot": "launcher", "issued_at": ISSUED,
                                            "env": {"FLUTTER_ROOT": SECRET_VALUES[0], "PUB_CACHE_SLOT_TEST": "old"}})
    reply = call("runtime.workspace.slot.env.set", {
        "workspace_id": workspace, "slot": "launcher", "issued_at": LATER,
        "env": {"PUB_CACHE_SLOT_TEST": "new"}, "env_keep": ["FLUTTER_ROOT", "PUB_CACHE_SLOT_TEST", "NEVER_STORED"],
    })["result"]
    assert slot_fill(workspace, "launcher").env == {"FLUTTER_ROOT": SECRET_VALUES[0], "PUB_CACHE_SLOT_TEST": "new"}
    assert reply["env_keep_missing"] == ["NEVER_STORED"]
    assert reply["fill"]["env_keys"] == ["FLUTTER_ROOT", "PUB_CACHE_SLOT_TEST"]
    # Positive control: without env_keep the set still REPLACES — the kept key is gone.
    call("runtime.workspace.slot.env.set", {"workspace_id": workspace, "slot": "launcher", "issued_at": LATER,
                                            "env": {"PUB_CACHE_SLOT_TEST": "new"}})
    assert slot_fill(workspace, "launcher").env == {"PUB_CACHE_SLOT_TEST": "new"}


def test_env_keep_must_name_keys(workspace):
    _declare(workspace, [_slot()])
    reply = call("runtime.workspace.slot.env.set", {"workspace_id": workspace, "slot": "launcher", "issued_at": ISSUED,
                                                     "env_keep": [3]})
    assert reply["error"]["data"]["reason"] == "invalid_fill"
