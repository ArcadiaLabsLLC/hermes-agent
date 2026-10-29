"""The Project record hermes keeps (plan project-slots-and-shared-chats-2026-10-29 §2, row RT-PROJECT-RECORD-STORE)."""

from __future__ import annotations

import json

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.project_store import ProjectStore, load_project
from agent_runtime.project_sync import apply_project_pull, held_project, merge_projects, publish_artifacts
from agent_runtime.realm_sync.families import SyncFamily, _destination_for_sync_path, _kind_for_sync_path
from agent_runtime.store import RealmStore, WorkspaceStore
from agent_runtime.workspace_projects import set_project_connection
from agent_runtime.workspace_slots import SlotRefused

OLD = "2026-10-29T10:00:00+00:00"
NEW = "2026-10-29T12:00:00+00:00"
CLONED = {"name": "launcher", "repo": {"clone_url": "https://example.com/launcher.git"},
          "context": {"files": ["CLAUDE.md"], "document_dirs": ["docs"], "adr_dirs": ["Launcher_Brain/30"]}}
LOCAL = {"name": "notes", "repo": {"local": True}}


def _declare(project="p1", slots=(CLONED, LOCAL), issued_at=OLD, store=None):
    return (store or ProjectStore()).declare(project, list(slots), issued_at=issued_at, machine="mach_a", name="Eternia")


def _make_remote(realm_id):
    """Bind a realm to a server after its workspaces were connected: its publish now needs a credential."""

    realm = RealmStore().get(realm_id)
    realm.server_id = "server"
    realm.sync_manifest_ref = "https://github.com/example/realm.git"
    RealmStore().save(realm)


def _assign(project, realm_id=None, name="ws"):
    workspace = WorkspaceStore().create(name=name, realm_id=realm_id).id
    set_project_connection(workspace, project, connected=True, expected_revision=0)
    return workspace


def test_the_record_round_trips_slots_categories_and_guidance():
    result = _declare()
    assert result["declared"] == ["launcher", "notes"]
    store = ProjectStore()
    store.set_category("p1", "documents", slot="launcher", subpath="docs/shared", shared=True, issued_at=OLD)
    store.set_category("p1", "guidance", slot=None, subpath=None, shared=True, issued_at=OLD)
    store.set_guidance("p1", description="The launcher", instructions="Be kind.", issued_at=OLD)
    record = load_project("p1")
    assert record["name"] == "Eternia" and record["project_id"] == "p1"
    assert record["slots"]["launcher"]["context"]["document_dirs"] == ["docs"]
    assert record["slots"]["launcher"]["context"]["adr_dirs"] == ["Launcher_Brain/30"]
    assert record["categories"]["documents"] == {"slot": "launcher", "subpath": "docs/shared", "shared": True,
                                                 "issued_at": OLD, "revision": 1}
    assert record["guidance"]["instructions"] == "Be kind."
    assert json.loads(paths.project_path("p1").read_text(encoding="utf-8")) == record
    # Turning the guidance share off takes the text out of the record: it never syncs unshared.
    store.set_category("p1", "guidance", slot=None, subpath=None, shared=False, issued_at=NEW)
    assert "guidance" not in load_project("p1")


def test_a_category_on_a_local_slot_refuses_to_share():
    _declare()
    store = ProjectStore()
    with pytest.raises(SlotRefused) as refused:
        store.set_category("p1", "chats", slot="notes", subpath=None, shared=True, issued_at=OLD)
    assert refused.value.reason == "category_not_source_controlled"
    assert "chats" not in load_project("p1")["categories"]
    # Positive control: the same folder, unshared, is declared; the cloned slot shares.
    assert store.set_category("p1", "chats", slot="notes", subpath=None, shared=False, issued_at=OLD)["record"]["subpath"] == ".eternia/chats"
    assert store.set_category("p1", "chats", slot="launcher", subpath=None, shared=True, issued_at=NEW)["record"]["shared"]


def test_making_a_shared_categorys_slot_local_unshares_it_at_the_declare():
    _declare()
    ProjectStore().set_category("p1", "boards", slot="launcher", subpath="brain", shared=True, issued_at=OLD)
    result = _declare(slots=({"name": "launcher", "repo": {"local": True}}, LOCAL), issued_at=NEW)
    assert result["categories_unshared"] == ["boards"]
    assert load_project("p1")["categories"]["boards"]["shared"] is False


def test_guidance_needs_its_switch_on():
    _declare()
    with pytest.raises(SlotRefused) as refused:
        ProjectStore().set_guidance("p1", description="d", instructions="i", issued_at=OLD)
    assert refused.value.reason == "guidance_not_shared"


def test_a_project_in_two_realms_needs_both_rights_and_the_refusal_names_the_denied_one():
    open_realm, shut = RealmStore().create(name="Open").id, RealmStore().create(name="Shut").id
    _assign("p1", open_realm, "a")
    held = _assign("p1", shut, "b")
    _make_remote(shut)
    with pytest.raises(SlotRefused) as refused:
        _declare()
    assert refused.value.reason == "realm_publish_denied" and refused.value.detail.startswith(shut)
    assert not paths.project_path("p1").exists()
    # Positive control: drop the denied realm's workspace and the same declare lands.
    WorkspaceStore().archive(held)
    assert _declare()["declared"] == ["launcher", "notes"]


def test_a_project_held_by_no_realm_is_this_machines_own():
    _assign("p1")
    assert _declare()["declared"]


def test_a_retried_older_write_is_stale():
    _declare(issued_at=NEW)
    with pytest.raises(SlotRefused) as refused:
        _declare(issued_at=OLD)
    assert refused.value.reason == "stale_revision"


def test_a_project_held_by_two_realms_publishes_into_each():
    one, two = RealmStore().create(name="One").id, RealmStore().create(name="Two").id
    _assign("p1", one, "a")
    _assign("p1", two, "b")
    _declare()
    for realm_id in (one, two):
        workspaces = [ws for ws in WorkspaceStore().list_all() if ws.realm_id == realm_id]
        artifacts = publish_artifacts(workspaces)
        assert [a.relative_path for a in artifacts] == [f"store/projects/{paths.project_path('p1').name}"]
        assert artifacts[0].kind == SyncFamily.PROJECT


def test_the_family_owns_its_path():
    rel = "store/projects/p1.json"
    assert _kind_for_sync_path(rel) == SyncFamily.PROJECT
    assert _destination_for_sync_path(rel) is None


def _peer(slots, categories=None, **extra):
    return {"schema_version": 1, "project_id": "p1", "name": "Peer", "issued_at": NEW, "slots": slots,
            "categories": categories or {}, "machines": {}, **extra}


def _slot(url="https://example.com/launcher.git", issued_at=NEW):
    return {"repo": {"clone_url": url, "default_branch": "main"}, "toolchain": {}, "context": {"files": ["CLAUDE.md"]},
            "recipe": {"revision": 0, "steps": []}, "issued_at": issued_at, "removed_at": None}


def test_the_applier_drops_a_malformed_peer_slot_whole_and_keeps_the_good_one(tmp_path):
    _declare()
    published = tmp_path / "store" / "projects"
    published.mkdir(parents=True)
    peer = _peer({"launcher": _slot(url="https://user:pw@example.com/x.git"), "backend": _slot()},
                 {"documents": {"slot": "backend", "subpath": "docs", "shared": True, "issued_at": NEW, "revision": 3},
                  "bogus": {"slot": None}})
    (published / paths.project_path("p1").name).write_text(json.dumps(peer), encoding="utf-8")
    summary = apply_project_pull("realm", tmp_path)
    reasons = {(row.get("slot") or row.get("category")): row["reason"] for row in summary.refused}
    assert reasons == {"launcher": "clone_url_carries_credential", "unknown": "invalid_category"}
    record = load_project("p1")
    assert record["slots"]["launcher"]["repo"]["clone_url"] == "https://example.com/launcher.git"
    assert record["slots"]["backend"]["repo"]["clone_url"] == "https://example.com/launcher.git"
    assert record["categories"]["documents"]["shared"] is True and record["name"] == "Peer"
    assert apply_project_pull("realm", tmp_path).changed is False


def test_a_peer_share_on_a_slot_this_side_made_local_is_unshared_by_the_merge():
    local = _peer({"launcher": {**_slot(), "repo": {"clone_url": None, "default_branch": "main", "local": True},
                                "recipe": {"revision": 2, "steps": []}}})
    remote = _peer({"launcher": _slot(issued_at=OLD)},
                   {"chats": {"slot": "launcher", "subpath": ".eternia/chats", "shared": True, "issued_at": NEW,
                              "revision": 1}}, guidance={"description": "", "instructions": "x", "issued_at": NEW,
                                                         "revision": 1})
    merged = merge_projects(local, remote)
    assert merged["categories"]["chats"]["shared"] is False
    assert "guidance" not in merged  # its switch was never on


def test_a_peer_guidance_past_the_bound_drops():
    held, refused = held_project(_peer({}, guidance={"description": "", "instructions": "x" * 32001,
                                                     "issued_at": NEW, "revision": 1}))
    assert "guidance" not in held and refused == [{"field": "guidance", "reason": "invalid_guidance"}]


def _rpc(verb, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": verb, "params": params})


def test_the_verbs_carry_the_store_and_its_typed_refusals():
    reply = _rpc("runtime.project.declare", project_id="p1", slots=[CLONED, LOCAL], issued_at=OLD, name="E")
    assert reply["result"]["declared"] == ["launcher", "notes"]
    refused = _rpc("runtime.project.category.set", project_id="p1", category="chats", slot="notes", shared=True,
                   issued_at=OLD)
    assert refused["error"]["data"]["reason"] == "category_not_source_controlled"
    assert _rpc("runtime.project.show", project_id="p1")["result"]["document"]["name"] == "E"
    assert _rpc("runtime.project.show", project_id="../x")["error"]["data"]["reason"] == "invalid_reference"
    tiers = serve_rpc.manifest()["tiers"]
    assert {tiers[name] for name in tiers if name.startswith("runtime.project.")} == {"console"}
