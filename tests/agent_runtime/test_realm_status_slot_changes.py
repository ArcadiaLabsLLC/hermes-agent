"""`realm sync status` says a workspace slot added, edited or removed waits for the publish.

RT-REALM-SLOTS-ADDED-WAIT-UNSEEN-UNTIL-A-HAND-PUBLISH: the owner added a slot to his shared realm, the
status read ``unpublished_changes: false``, so nothing prompted a publish and his teammate never saw the
slot. Seen live 2026-11-16 (w1115e-rs, staging, two accounts). The status now asks the publish's own
compare (``publish.publish_set_changes``), so every family the publish writes counts. A machine's own
``machines.<id>`` report, re-stamped by every re-probe, does not (owner RULED 2026-11-16).

Pinned through the app's doors: ``runtime.workspace.slots.declare`` and ``runtime.realm.sync.status``.
Killing mutations are named per test.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import live_slots, load_document
from tests.agent_runtime.test_workspace_move_leaves_every_realm import _own_realm
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _shared_workspace, _Team

CLONE_URL = "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git"
STAMPS = ("2026-11-16T10:00:00+00:00", "2026-11-16T11:00:00+00:00", "2026-11-16T12:00:00+00:00")


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _call(method: str, params: dict) -> dict:
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})
    assert "error" not in reply, reply
    return reply["result"]


def _slot(name: str, branch: str = "main") -> dict:
    return {"name": name, "repo": {"clone_url": CLONE_URL, "default_branch": branch}, "context": {"role": "docs"}}


def _declare(workspace_id: str, slots: list[dict], issued_at: str) -> None:
    _call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": slots, "issued_at": issued_at})


def _slot_waiting(realm_id: str) -> tuple[bool, list[str]]:
    """``(unpublished_changes, the slot documents the next publish would write)`` as the app reads them."""
    status = _call("runtime.realm.sync.status", {"realm_id": realm_id})
    return status["unpublished_changes"], [p for p in status["publish_changes"] if p.startswith("store/workspace_slots/")]


def _reprobe(workspace_id: str) -> None:
    from agent_runtime.workspace_slots_probe import report

    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=CLONE_URL + "\n", stderr="")

    report(workspace_id, run=runner)


def test_a_slot_added_edited_or_removed_lights_the_flag_until_the_publish(team):
    """One player, her own realm: each slot change lights "unpublished changes", naming the slot document,
    until she publishes; a re-probe alone does not (owner RULED 2026-11-16).

    Mutations: drop ``or publish_changes`` from ``unpublished_changes`` in ``realm_sync_status`` -> the flag
    reads False over the added slot, red (the owner's report); in ``publish_set_changes`` make ``_counts``
    answer True for a slot document -> the re-probe lights the flag, red."""
    home = _own_realm(team, "desk", "Home")
    workspace = WorkspaceStore().create(name="Docs", realm_id=home.id)
    publish_realm_sync(home.id)
    assert _slot_waiting(home.id) == (False, [])
    document = f"store/workspace_slots/{workspace.id}.json"

    for stamp, slots in zip(STAMPS, ([_slot("rsdocs")], [_slot("rsdocs", branch="dev")], [])):
        _declare(workspace.id, slots, stamp)
        assert _slot_waiting(home.id) == (True, [document])
        publish_realm_sync(home.id)
        assert _slot_waiting(home.id) == (False, [])
        _reprobe(workspace.id)
        assert _slot_waiting(home.id) == (False, [])


def test_a_slot_the_owner_adds_reaches_the_member_on_the_next_pull_after_his_publish(team):
    """Alice adds, edits and removes ``rsdocs`` in the shared realm; each waits in her status, and each
    publish carries it to Bob. The team fixture's members share one skills folder, which lights the flag on
    its own, so this one reads the slot paths (the own-realm test above pins the flag).

    Mutation: in ``publish_set_changes`` return ``[]`` -> no slot document named while it waits, red."""
    shared, workspace = _shared_workspace(team)
    document = f"store/workspace_slots/{workspace.id}.json"

    for stamp, slots in zip(STAMPS, ([_slot("rsdocs")], [_slot("rsdocs", branch="dev")], [])):
        team.be("alice")
        _declare(workspace.id, slots, stamp)
        assert _slot_waiting(shared.id)[1] == [document]
        publish_realm_sync(shared.id)
        assert _slot_waiting(shared.id)[1] == []
        team.be("bob")
        pull_realm_sync(shared.id)
        held = live_slots(load_document(workspace.id))
        assert {name: slot["repo"]["default_branch"] for name, slot in held.items()} == {
            slot["name"]: slot["repo"]["default_branch"] for slot in slots}


def test_a_member_s_re_probe_waits_for_nothing_and_the_reports_ride_the_next_real_publish(team):
    """Mutation: in ``publish_set_changes`` make ``_counts`` answer True for a slot document -> Bob's
    re-probe names the slot document as waiting, red."""
    shared, workspace = _shared_workspace(team)
    _declare(workspace.id, [_slot("rsdocs")], STAMPS[0])
    publish_realm_sync(shared.id)
    team.be("bob")
    pull_realm_sync(shared.id)

    for member in ("alice", "bob"):
        team.be(member)
        _reprobe(workspace.id)
        assert load_document(workspace.id).get("machines"), "the re-probe wrote no report"
        assert _slot_waiting(shared.id)[1] == []

    # Alice's report travels with her next real publish, verbatim.
    document = f"store/workspace_slots/{workspace.id}.json"
    team.be("alice")
    _declare(workspace.id, [_slot("rsdocs"), _slot("rsassets")], STAMPS[1])
    publish_realm_sync(shared.id)
    team.be("bob")
    pull_realm_sync(shared.id)
    assert set(live_slots(load_document(workspace.id))) == {"rsdocs", "rsassets"}
    published = json.loads((team.clone("alice", "srv_team") / "realms" / paths.safe_path_token(shared.id)
                            / document).read_text(encoding="utf-8"))
    assert published["machines"], "the real publish did not carry the machine report"
