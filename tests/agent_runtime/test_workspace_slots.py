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


def test_declare_one_slot_keeps_the_other_slots(workspace):
    """The second write site (p10-work §2.5): one name in, nothing tombstoned — the positive control
    against ``declare``'s REPLACE. Killing mutation: ``declare_one_slot`` delegating to ``declare([entry])``
    tombstones ``backend`` and this goes red."""

    from agent_runtime.workspace_slots import declare_one_slot

    _declare(workspace, [_slot("launcher"), _slot("backend")])
    reply = declare_one_slot(workspace, _slot("brain"), issued_at=LATER, machine="m-1")
    assert reply["declared"] == ["brain"] and reply["tombstoned"] == []
    slots = load_document(workspace)["slots"]
    assert {name for name, slot in slots.items() if not slot.get("removed_at")} == {"launcher", "backend", "brain"}
    assert slots["brain"]["declared_by_machine"] == "m-1" and load_document(workspace)["issued_at"] == LATER
    with pytest.raises(Exception) as stale:
        declare_one_slot(workspace, _slot("brain"), issued_at=ISSUED, machine="m-1")
    assert getattr(stale.value, "reason", None) == "stale_revision"


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
    held = load_machine_roots(refresh=True)
    assert held.workspace_root(workspace, "launcher") == checkout and "launcher" not in held.roots
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
    assert here["bound_here"] is False and here["path"] is None and here["folder_missing"] is False
    [entry] = here["unknowns"]
    assert entry["kind"] == "slot_unbound_here" and "mach_far" in entry["evidence"] and "mach_none" not in entry["evidence"]


def test_a_deleted_bound_folder_keeps_its_path_and_says_folder_missing(workspace, checkout):
    """RT-SLOTS-SHOW-DROPS-MISSING-PATH: "folder missing" is not "not set up on this machine"."""

    _declare(workspace, [_slot()])
    call("runtime.workspace.slot.bind", {"workspace_id": workspace, "slot": "launcher", "path": str(checkout),
                                         "issued_at": ISSUED})
    here = call("runtime.workspace.slots.show", {"workspace_id": workspace})["result"]["here"]["launcher"]
    assert (here["bound_here"], here["path"], here["folder_missing"]) == (True, str(checkout), False)
    checkout.rename(checkout.with_name("launcher-gone"))
    here = call("runtime.workspace.slots.show", {"workspace_id": workspace})["result"]["here"]["launcher"]
    assert (here["bound_here"], here["path"], here["folder_missing"]) == (False, str(checkout), True)


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


def _snapshot_row(workspace):
    from agent_runtime.snapshot import workspace_summary

    item = next(ws for ws in WorkspaceStore().list_all(include_archived=True) if ws.id == workspace)
    return workspace_summary(item)["repo_slots"]


def test_the_snapshot_workspace_row_carries_slot_names_and_this_machines_last_report(workspace, checkout):
    _declare(workspace, [_slot("launcher"), _slot("backend")])
    assert _snapshot_row(workspace) == {
        "slots": {"backend": {"bound_here": False, "status": None, "checkout": None},
                  "launcher": {"bound_here": False, "status": None, "checkout": None}},
        "reported_at": None,
    }
    call("runtime.workspace.slot.bind", {"workspace_id": workspace, "slot": "launcher", "path": str(checkout),
                                         "issued_at": ISSUED})
    row = _snapshot_row(workspace)
    assert row["slots"]["launcher"] == {"bound_here": True, "status": "needs_setup", "checkout": "matches"}
    assert row["slots"]["backend"] == {"bound_here": False, "status": "not_cloned", "checkout": None}
    assert row["reported_at"]
    # No path and never a value on the frame.
    shown = json.dumps(row)
    for value in (str(checkout), json.dumps(str(checkout))[1:-1], *SECRET_VALUES):
        assert value not in shown


def test_a_tombstoned_slot_leaves_the_snapshot_row(workspace):
    _declare(workspace, [_slot("launcher"), _slot("backend")])
    _declare(workspace, [_slot("launcher")], issued_at=LATER)
    assert list(_snapshot_row(workspace)["slots"]) == ["launcher"]


def test_a_local_slot_round_trips_normalize_declaration(workspace):
    """A ``repo.local`` slot (the Work default brain, work-on-markdown §4) needs no clone URL and keeps ``local``."""

    from agent_runtime.workspace_slots import SlotRefused, normalize_declaration

    entry = {"name": "brain", "repo": {"clone_url": None, "default_branch": "main", "local": True},
             "context": {"role": "brain", "brain_dir": "Work_Brain/20 — Active Initiatives"}}
    name, body = normalize_declaration(entry)
    assert name == "brain" and body["repo"] == {"clone_url": None, "default_branch": "main", "local": True}
    assert body["context"]["brain_dir"] == "Work_Brain/20 — Active Initiatives"
    assert normalize_declaration({**entry, **body, "name": name}) == (name, body)  # the launcher's re-declare
    assert "result" in _declare(workspace, [entry])
    assert load_document(workspace)["slots"]["brain"]["repo"]["local"] is True
    # A clone URL makes the slot an ordinary one; no URL and no ``local`` is still refused.
    named = normalize_declaration({**entry, "repo": {"clone_url": CLONE_URL, "local": True}})[1]["repo"]
    assert "local" not in named and named["clone_url"] == CLONE_URL
    with pytest.raises(SlotRefused) as refused:
        normalize_declaration({"name": "brain", "repo": {"clone_url": None}})
    assert refused.value.reason == "invalid_clone_url"
    with pytest.raises(SlotRefused) as escaping:
        normalize_declaration({**entry, "context": {"brain_dir": "../outside"}})
    assert escaping.value.reason == "invalid_declaration"


def test_context_gate_round_trips_and_refuses_a_credential(workspace):
    """``context.gate`` (p10-work §3 G1): the slot's landing-gate commands, synced like the rest of ``context``.

    Killing mutation, red recorded in its commit body: ``_context`` drops the ``gate`` key → this test red.
    """

    from agent_runtime.workspace_slots import SlotRefused, normalize_declaration

    entry = {"name": "launcher", "repo": {"clone_url": CLONE_URL, "default_branch": "main"},
             "toolchain": {"kind": "flutter"},
             "context": {"role": "frontend", "gate": [" dart tool/heavy_run/run.dart -- dart tool/run_tier.dart "]}}
    name, body = normalize_declaration(entry)
    assert body["context"]["gate"] == ["dart tool/heavy_run/run.dart -- dart tool/run_tier.dart"]
    assert normalize_declaration({**entry, **body, "name": name}) == (name, body)
    assert "gate" not in normalize_declaration({**entry, "context": {"role": "frontend"}})[1]["context"]
    assert normalize_declaration({**entry, "context": {"gate": []}})[1]["context"]["gate"] == []
    assert "result" in _declare(workspace, [entry])
    assert load_document(workspace)["slots"]["launcher"]["context"]["gate"] == body["context"]["gate"]
    for bad in (["git push https://me:hunter2@github.com/x/y.git"], "bash scripts/test.sh", [""], [3]):
        with pytest.raises(SlotRefused) as refused:
            normalize_declaration({**entry, "context": {"gate": bad}})
        assert refused.value.reason == "invalid_declaration", bad


# ── Slot roots per workspace (plan work-slot-roots-per-workspace-2026-10-21 R2) ──


def _bare_dir(tmp_path, name):
    target = tmp_path / "dirs" / name
    target.mkdir(parents=True)
    return target


def test_two_workspaces_binding_one_slot_name_keep_their_own_paths(workspace, tmp_path):
    """Killing mutation: ``bind`` writing ``roots[slot]`` as before — ws1 reads ws2's directory."""

    from agent_runtime.workspace_slots import bind, bound_path, slot_census

    other = WorkspaceStore().create(name="Slots two").id
    one, two = _bare_dir(tmp_path, "one"), _bare_dir(tmp_path, "two")
    for ws in (workspace, other):
        _declare(ws, [_slot("brain")])
    bind(workspace, "brain", str(one), issued_at=ISSUED)
    bind(other, "brain", str(two), issued_at=ISSUED)
    assert bound_path("brain", workspace_id=workspace) == one
    assert bound_path("brain", workspace_id=other) == two
    bound = {(slot.workspace_id, slot.slot): slot.path for slot in slot_census().bound}
    assert bound[(workspace, "brain")] == one and bound[(other, "brain")] == two


def test_a_bind_never_writes_a_config_root_and_two_folders_are_ambiguous_unscoped(workspace, tmp_path):
    """Killing mutation: restoring ``roots.setdefault(slot, path)`` in ``_write_fill`` — first bind wins."""

    from agent_runtime.machine_roots import ISSUE_ROOT_AMBIGUOUS, expand_config_paths, path_token_issues
    from agent_runtime.workspace_slots import bind

    other = WorkspaceStore().create(name="Slots two").id
    first, second = _bare_dir(tmp_path, "first"), _bare_dir(tmp_path, "second")
    for ws in (workspace, other):
        _declare(ws, [_slot("eternia_launcher")])
    bind(workspace, "eternia_launcher", str(first), issued_at=ISSUED)
    roots = load_machine_roots(refresh=True)
    assert "eternia_launcher" not in roots.roots
    assert expand_config_paths("${roots.eternia_launcher}", roots=roots) == str(first)  # one folder: resolves
    bind(other, "eternia_launcher", str(second), issued_at=ISSUED)
    roots = load_machine_roots(refresh=True)
    assert "eternia_launcher" not in roots.roots
    assert [i.code for i in path_token_issues("${roots.eternia_launcher}", roots=roots)] == [ISSUE_ROOT_AMBIGUOUS]
    assert expand_config_paths("${roots.eternia_launcher}", roots=roots, workspace_id=other) == str(second)


# ── The one-time legacy migration (plan work-slot-roots-per-workspace-2026-10-21 R3) ──


def _receipts(caplog, kind):
    return [json.loads(r.getMessage()) for r in caplog.records
            if r.name == "agent_runtime.work_store.receipts" and f'"kind": "{kind}"' in r.getMessage()]


def _legacy_registry(roots):
    from agent_runtime.machine_roots import machine_roots_registry_paths

    target = machine_roots_registry_paths()[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"schema_version": 1, "roots": roots}), encoding="utf-8")
    machine_roots_cache_clear()
    return target


def test_a_legacy_root_migrates_once_to_the_workspace_declaring_it(workspace, checkout, caplog):
    import logging

    from agent_runtime.workspace_slots import slot_census

    caplog.set_level(logging.INFO, logger="agent_runtime.work_store.receipts")
    _declare(workspace, [_slot("brain")])
    target = _legacy_registry({"brain": str(checkout)})
    assert [(s.workspace_id, s.slot, s.path) for s in slot_census().bound] == [(workspace, "brain", checkout)]
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["schema_version"] == 3 and written["slot_folders"] == {workspace: {"brain": str(checkout)}}
    assert written["config_roots"] == {"brain": str(checkout)}  # schema 1's roots were bound by hand: kept
    assert written["roots"] == {"brain": str(checkout)}  # the config namespace is kept as it was
    [receipt] = _receipts(caplog, "machine_roots.migrated")
    assert (receipt["workspaces"], receipt["slots"]) == (1, 1)
    slot_census()
    assert len(_receipts(caplog, "machine_roots.migrated")) == 1  # once


def test_an_ambiguous_legacy_root_binds_only_the_workspace_whose_origin_matches(workspace, checkout, caplog):
    """Killing mutation: migrating an ambiguous name to the FIRST workspace binds the non-matching one."""

    import logging

    from agent_runtime.workspace_slots import bound_path, realm_workspace_ids

    caplog.set_level(logging.INFO, logger="agent_runtime.work_store.receipts")
    other = WorkspaceStore().create(name="Slots two").id
    _declare(workspace, [_slot("brain")])
    _declare(other, [_slot("brain")])
    first = next(ws for ws in realm_workspace_ids() if ws in (workspace, other))
    mismatched = first  # the first claimant is the wrong one, so "first wins" is caught
    matched = other if first == workspace else workspace
    _declare(mismatched, [_slot("brain", repo={"clone_url": "https://example.com/other.git"})], issued_at=LATER)
    _legacy_registry({"brain": str(checkout)})
    assert bound_path("brain", workspace_id=matched) == checkout
    assert bound_path("brain", workspace_id=mismatched) is None
    [entry] = _receipts(caplog, "machine_roots.migration_ambiguous")
    assert entry["slot"] == "brain" and entry["unbound"] == [mismatched]
    assert sorted(entry["workspaces"]) == sorted([workspace, other])


def _mirrored_registry(roots, scoped):
    from agent_runtime.machine_roots import machine_roots_registry_paths

    target = machine_roots_registry_paths()[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"schema_version": 2, "roots": roots, "workspace_roots": scoped}), encoding="utf-8")
    machine_roots_cache_clear()
    return target


def test_a_schema_2_registry_upgrades_once_dropping_only_single_binding_mirrors(workspace, tmp_path, caplog):
    """Killing mutation: ``_without_slot_mirrors`` keeping every entry leaves ``brain``'s mirror a config root."""

    import logging

    from agent_runtime.workspace_slots import scoped_roots

    caplog.set_level(logging.INFO, logger="agent_runtime.work_store.receipts")
    one, two, tool = _bare_dir(tmp_path, "one"), _bare_dir(tmp_path, "two"), _bare_dir(tmp_path, "tool")
    scoped = {"ws_a": {"brain": str(one), "launcher": str(one)}, "ws_b": {"launcher": str(two)}}
    target = _mirrored_registry({"brain": str(one), "launcher": str(one), "tool": str(tool)}, scoped)
    upgraded = scoped_roots()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["schema_version"] == 3 and written["slot_folders"] == scoped
    # ``brain`` was the mirror of its one binding; ``launcher`` has two bindings, so it may be an operator's.
    assert written["config_roots"] == {"launcher": str(one), "tool": str(tool)}
    assert written["roots"] == {"brain": str(one), "launcher": str(one), "tool": str(tool)}
    assert upgraded.roots == written["config_roots"] and upgraded.schema_version == 3
    [receipt] = _receipts(caplog, "machine_roots.migrated")
    assert (receipt["from_schema"], receipt["mirrors_dropped"], receipt["config_roots"]) == (2, 1, 2)
    before = target.read_text(encoding="utf-8")
    scoped_roots()
    assert target.read_text(encoding="utf-8") == before and len(_receipts(caplog, "machine_roots.migrated")) == 1
