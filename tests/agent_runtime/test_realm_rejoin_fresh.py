"""Leaving a server and joining it again: the local copy stays yours under its own ids, and the server's realm
comes back fresh beside it (RT-REJOIN-PULLS-THE-SERVER-REALM-FRESH; plan
``docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md`` §5, §7, §9 slice 6).

The realm is the census test's — real stores, a bare team repository, two agents at desks with chats — driven
through the entry points Eternia uses: ``runtime.realm.revoked``, ``runtime.realm.adopt`` (the backend's grant
list stood in at the one HTTP function), ``runtime.workspace.move_realm``, and the realm pull. The same walk
through a real ``hermes harness serve`` child is the lane's real-path run. Killing mutations are named per test."""
import json

import pytest

from agent_runtime import paths as runtime_paths
from agent_runtime import realm_membership, serve_rpc, turn_activity
from agent_runtime.board_models import default_board_id
from agent_runtime.board_store import BoardStore
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_instance_sync.sidecars import instance_conflict_path
from agent_runtime.realm_rekey import OWED_HANDLERS, RekeyState, read_rekey_journal, rekeyed_from
from agent_runtime.realm_rekey_agents import parked_agents_dir
from agent_runtime.realm_rekey_triggers import RekeyTrigger, run_owed_rekeys
from agent_runtime.realm_sync import pull_realm_sync
from agent_runtime.realm_sync.revocation import RealmRevokedReason, read_realm_shared_from, write_realm_shared_from
from agent_runtime.store import RealmStore, WorkspaceStore
from tests.agent_runtime.test_realm_rekey_census import HELPER, LEAD, _git, _left_realm, _session_ids, _titles

CREDENTIAL = {
    "schema_version": 1, "realm_id": "realm_team", "api_base": "https://api.test.invalid/api", "api_token": "etk_t",
    "git_url": "https://git.test.invalid/r.git", "git_authorization": "Basic x", "expires_at": "2999-01-01T00:00:00Z",
}


def _rpc(method, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "rj", "method": method, "params": params})


def _join(monkeypatch, tmp_path, realm_id="realm_team", default_workspace_id="ws_shared"):
    """``runtime.realm.adopt`` as Eternia sends it; the backend grants ``realm_id`` on ``srv_team``."""
    grant = {"id": realm_id, "server_id": "srv_team", "name": "Team", "slug": "team",
             "git_url": str(tmp_path / "team-clone"), "default_workspace_id": default_workspace_id,
             "default_workspace_name": "Shared"}
    monkeypatch.setattr(realm_membership, "_request_json", lambda *a, **k: (200, {"items": [grant]}))
    return _rpc("runtime.realm.adopt", credential={**CREDENTIAL, "realm_id": realm_id})


def _every_id() -> list[str]:
    """Every realm, workspace, board, card and agent id the stores hold, archived ones too."""
    cards = [path.stem for path in runtime_paths.boards_root().glob("*/*/*.json")]
    boards = [path.parent.name for path in runtime_paths.boards_root().glob("*/board.json")]
    return [*(item.id for item in RealmStore().list_all(include_archived=True)),
            *(item.id for item in WorkspaceStore().list_all(include_archived=True)),
            *boards, *cards, *(item.id for item in PersonaInstanceStore().list_all())]


def test_leave_then_rejoin_the_local_copy_keeps_your_changes_and_the_servers_realm_comes_back_fresh(tmp_path, monkeypatch):
    """Mutations: drop ``owe_rekey`` from ``make_realm_local`` -> ``rekey`` is None at the leave, red; drop the
    ``make_way`` call in ``adopt_realms`` (the old re-bind) -> the adopt binds the local copy's id again while
    the turn is live instead of refusing, red; drop ``restore_parked_agents`` from the pull -> the team's
    agents are minted anew and their chats are gone, red; drop the baseline it writes -> the agent renamed
    while local is held as a conflict, red; pass no ``only`` -> the agent the team removed comes back, red;
    drop ``_rewrite_membership`` -> Home still lists the workspace under the team's id, red; let ``owe_rekey``
    answer a ``done`` journal -> the second leave is never re-keyed, red."""
    assert OWED_HANDLERS == {}  # the leave may owe a re-key only while every MOVES place has its step
    realm, first, second, extra, team_head = _left_realm(tmp_path)  # left while a turn was live: owed
    team = {item.id: item for item in PersonaInstanceStore().list_all() if item.id in (LEAD, HELPER)}
    team_chats = {item.default_chat_session_id for item in team.values()}
    owed = read_rekey_journal(realm.id)
    assert (owed["state"], owed["reason"]) == (RekeyState.OWED.value, "membership_left")

    # While local, still under the team's ids: a rename of a team agent, a move, an archive.
    PersonaInstanceStore().patch_fields(HELPER, display_name="Renamed while local")
    home = RealmStore().create(name="Home")
    moved = _rpc("runtime.workspace.move_realm", workspace_id=second.id, realm_id=home.id)["result"]
    assert moved["moved"] is True
    spare = WorkspaceStore().create(name="Spare", realm_id=realm.id)
    WorkspaceStore().archive(spare.id)

    # A re-join while a turn is live: refused, retryable, nothing adopted, nothing moved.
    with turn_activity.admitted_turn("still working"):
        refused = _join(monkeypatch, tmp_path)["error"]
    assert (refused["data"]["reason"], refused["data"]["retryable"], refused["data"]["running"],
            refused["data"]["realm_id"], refused["data"]["retry_after_ms"]) == ("realm_busy", True, "turn", realm.id, 5000)
    assert RealmStore().get(realm.id).server_id is None and read_rekey_journal(realm.id)["state"] == RekeyState.OWED.value

    # Idle: the owed re-key runs by itself.
    [attempt] = run_owed_rekeys(RekeyTrigger.IDLE)
    mapping = attempt.journal["map"]
    local, new_first, new_second = mapping["realm_new"], mapping["workspaces"][first.id], mapping["workspaces"][second.id]
    assert attempt.done and realm.id not in {item.id for item in RealmStore().list_all(include_archived=True)}
    home_now = RealmStore().get(home.id)
    assert WorkspaceStore().get(new_second).realm_id == home.id and home_now.workspace_ids == [new_second]
    assert spare.id in {item.id for item in WorkspaceStore().list_all(include_archived=True) if item.archived}
    assert sorted(path.stem for path in parked_agents_dir(realm.id).glob("*.json")) == sorted([LEAD, HELPER])

    # The team removes one agent while the member is away (another member's publish).
    clone = tmp_path / "team-clone"
    projection = clone / "realms" / realm.id / "store" / "persona_instances.yaml"
    text = projection.read_text(encoding="utf-8")
    assert LEAD in text and HELPER in text
    from agent_runtime import yaml_io

    document = yaml_io.load(text)
    rows = document["instances"] if "instances" in document else document
    removed = _drop_row(rows, LEAD)
    assert removed, "the published projection names the lead"
    projection.write_text(yaml_io.dump(document), encoding="utf-8")
    _git(clone, "commit", "-q", "-am", "another member removes the lead")
    _git(clone, "push", "-q", "origin", "HEAD")
    team_head = _git(tmp_path / "team.git", "rev-parse", "main")

    # The re-join: the server's realm is created fresh, beside the local copy.
    rows = _join(monkeypatch, tmp_path)["result"]["items"]
    assert [row["id"] for row in rows] == [realm.id]
    fresh = RealmStore().get(realm.id)
    assert (fresh.server_id, fresh.sync_manifest_ref, fresh.workspace_ids) == ("srv_team", str(clone), [first.id])
    assert RealmStore().get(local).server_id is None and read_realm_shared_from(local)["server_id"] == "srv_team"
    assert read_realm_shared_from(realm.id) is None
    assert rekeyed_from(local)["realm_id"] == realm.id and rekeyed_from(realm.id) is None
    pull_realm_sync(realm.id)

    # Fresh == the team's copy: its workspaces, its cards, its agents with their chats; nothing local in it.
    assert {item.id for item in WorkspaceStore().list_all() if item.realm_id == realm.id} == {first.id, second.id}
    assert _titles(first.id) == {default_board_id(first.id): ["Team card"]}
    assert _titles(second.id)[extra.board_id] == ["On the extra board"]
    back = PersonaInstanceStore().get(HELPER)
    assert (back.display_name, back.workspace_id, back.realm_id, back.default_chat_session_id) == (
        team[HELPER].display_name, first.id, realm.id, team[HELPER].default_chat_session_id)
    assert not instance_conflict_path(realm.id, HELPER).exists()
    assert team_chats <= _session_ids()
    live = {item.id for item in PersonaInstanceStore().list_all()}
    assert LEAD not in live  # the team removed it: it stays parked, its chat on disk
    assert [path.stem for path in parked_agents_dir(realm.id).glob("*.json")] == [LEAD]
    # The local copy: every change made while local, under its own ids, with its own agents.
    assert _titles(new_first) == {default_board_id(new_first): ["Added while local", "Team card"]}
    assert WorkspaceStore().get(new_second).realm_id == home.id
    assert {mapping["agents"][LEAD], mapping["agents"][HELPER]} <= live
    assert PersonaInstanceStore().get(mapping["agents"][HELPER]).display_name == "Renamed while local"
    # Nothing done while local reached the team, and no id is held twice.
    assert _git(tmp_path / "team.git", "rev-parse", "main") == team_head
    ids = _every_id()
    assert sorted(ids) == sorted(set(ids)), [item for item in ids if ids.count(item) > 1]

    # A second cycle: leave again (nothing running: re-keyed at once), join again.
    left = _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_kicked")["result"]
    assert (left["became_local"], left["rekey"], left["rekey_waits_on"]) == (True, "done", None)
    second_local = left["rekeyed_to"]
    assert second_local not in (None, realm.id, local) and left["shared_from"]["reason"] == "membership_kicked"
    replay = _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_kicked")["result"]
    assert (replay["became_local"], replay["rekeyed_to"], replay["shared_from"]) == (False, second_local, left["shared_from"])
    assert (rekeyed_from(local)["realm_id"], rekeyed_from(second_local)["realm_id"]) == (realm.id, realm.id)
    assert [row["id"] for row in _join(monkeypatch, tmp_path)["result"]["items"]] == [realm.id]
    pull_realm_sync(realm.id)
    held = {item.id: item.server_id for item in RealmStore().list_all(include_archived=True)}
    assert {key: held[key] for key in (realm.id, local, second_local)} == {realm.id: "srv_team", local: None, second_local: None}
    assert PersonaInstanceStore().get(HELPER).default_chat_session_id == team[HELPER].default_chat_session_id
    ids = _every_id()
    assert sorted(ids) == sorted(set(ids)), [item for item in ids if ids.count(item) > 1]
    assert _git(tmp_path / "team.git", "rev-parse", "main") == team_head


def _drop_row(rows, instance_id: str) -> bool:
    """Remove ``instance_id`` from a projection document's rows (a mapping by id, or a list of bodies)."""
    if isinstance(rows, dict):
        return rows.pop(instance_id, None) is not None
    kept = [row for row in rows if row.get("id") != instance_id]
    removed = len(kept) != len(rows)
    rows[:] = kept
    return removed


def test_a_realm_left_before_the_rekey_existed_is_moved_aside_when_you_join_again(tmp_path, monkeypatch):
    """A local realm that still holds the server's realm id and owes nothing: left under the build that bound
    the same realm again (``shared_from``, no journal), with the baselines that build set aside.

    Mutations: drop the server-less arm of ``make_way_for_rejoin`` -> the adopt binds the local realm again
    (one realm, the local card in it), red; drop the legacy baselines removal in ``_step_ledgers`` -> the
    folder is still there under the new id, red."""
    realm = RealmStore().create(name="Team", realm_id="realm_team")
    workspace = WorkspaceStore().create(name="Shared", realm_id=realm.id, workspace_id="ws_shared")
    BoardStore().add_card(workspace_id=workspace.id, title="Made while local")
    write_realm_shared_from(realm.id, server_id="srv_team", server_name="The Guild", reason=RealmRevokedReason.MEMBERSHIP_LEFT)
    legacy = runtime_paths.store_root() / "realm_sync_state" / f"{realm.id}.team_baselines"
    legacy.mkdir(parents=True)
    (legacy / "board_baseline.json").write_text("{}", encoding="utf-8")
    assert read_rekey_journal(realm.id) is None

    rows = _join(monkeypatch, tmp_path)["result"]["items"]

    assert [row["id"] for row in rows] == [realm.id]
    journal = read_rekey_journal(realm.id)
    local = journal["map"]["realm_new"]
    assert (journal["state"], journal["reason"]) == (RekeyState.DONE.value, "rejoin")
    assert RealmStore().get(realm.id).server_id == "srv_team" and RealmStore().get(local).server_id is None
    assert read_realm_shared_from(local)["server_name"] == "The Guild"
    assert _titles(journal["map"]["workspaces"][workspace.id]) == {
        default_board_id(journal["map"]["workspaces"][workspace.id]): ["Made while local"]}
    assert _titles(workspace.id) == {}  # the fresh realm's default workspace: empty until its pull
    assert not list((runtime_paths.store_root() / "realm_sync_state").glob("*.team_baselines"))


def test_a_member_who_never_left_is_adopted_as_before(tmp_path, monkeypatch):
    """Mutation: re-key every granted realm this install holds (drop the ``held.server_id`` skip) -> a bound
    realm is moved aside on every adopt, red."""
    realm = RealmStore().create(name="Team", server_id="srv_team", realm_id="realm_team")
    workspace = WorkspaceStore().create(name="Shared", realm_id=realm.id, workspace_id="ws_shared")

    rows = _join(monkeypatch, tmp_path)["result"]["items"]

    assert [row["id"] for row in rows] == [realm.id] and read_rekey_journal(realm.id) is None
    assert [item.id for item in RealmStore().list_all()] == [realm.id]
    assert WorkspaceStore().get(workspace.id).realm_id == realm.id


@pytest.mark.parametrize("reason", ["grant_removed", "realm_deleted"])
def test_a_leave_with_nothing_running_takes_its_own_ids_at_once(tmp_path, reason):
    """Mutation: drop the ``run_owed_rekeys`` call from the leave -> ``rekey`` is ``owed`` with nothing
    running, red."""
    realm, first, _second, _extra, _head = _left_realm(tmp_path)
    run_owed_rekeys(RekeyTrigger.IDLE)
    other = RealmStore().create(name="Other", server_id="srv_other", realm_id="realm_other")
    WorkspaceStore().create(name="Theirs", realm_id=other.id, workspace_id="ws_theirs")

    left = _rpc("runtime.realm.revoked", realm_id=other.id, reason=reason, server_name="Other Guild")["result"]

    assert (left["became_local"], left["rekey"], left["rekey_waits_on"], left["realm_id"]) == (True, "done", None, other.id)
    local = RealmStore().get(left["rekeyed_to"])
    assert (local.name, local.server_id) == ("Other", None)
    assert left["shared_from"] == read_realm_shared_from(local.id) and left["shared_from"]["server_name"] == "Other Guild"
    assert json.loads(runtime_paths.workspace_path(read_rekey_journal(other.id)["map"]["workspaces"]["ws_theirs"]).read_text(
        encoding="utf-8"))["realm_id"] == local.id


def _map(name: str) -> bytes:
    return json.dumps({"version": 4, "name": name, "props": []}).encode("utf-8")


def test_the_fresh_pull_takes_what_the_team_changed_in_a_shared_catalogue_and_keeps_what_you_changed(tmp_path, monkeypatch):
    """Maps, prefabs, persona definitions, profile files and skills are this install's: one document serves the
    local copy and the server's realm. Three maps published while a member; after the leave the member edits
    one, the team edits another.

    Mutations: drop ``_keep_team_catalogues`` from ``owe_rekey`` (or ``restore_team_catalogues`` from
    ``make_way_for_rejoin``) -> the fresh realm has no map baseline and both edited maps are held as
    conflicts, the team's newer map never arrives, red; keep the baselines at the re-key instead of the leave
    (read the live folder after the local-era sync) -> not reachable here without a local-era map publish:
    pinned by the order in ``owe_rekey`` only."""
    from agent_runtime.map_sync import MapStore
    from tests.agent_runtime import test_realm_rekey_census as census

    publish = census.publish_realm_sync

    def publish_with_maps(realm_id, *args, **kwargs):
        if not MapStore().list_tokens():  # the seed's first publish, while still a member
            for token, name in (("map_same", "Same"), ("map_mine", "Mine v1"), ("map_team", "Team v1")):
                MapStore().write(token, _map(name))
        return publish(realm_id, *args, **kwargs)

    monkeypatch.setattr(census, "publish_realm_sync", publish_with_maps)
    realm, _first, _second, _extra, _head = _left_realm(tmp_path)
    MapStore().write("map_mine", _map("Mine v2, edited while local"))
    run_owed_rekeys(RekeyTrigger.IDLE)
    clone = tmp_path / "team-clone"
    [published] = list(clone.rglob("map_team.json"))
    published.write_bytes(_map("Team v2, edited by the team"))
    _git(clone, "commit", "-q", "-am", "the team edits a map")
    _git(clone, "push", "-q", "origin", "HEAD")

    _join(monkeypatch, tmp_path)
    maps = pull_realm_sync(realm.id)["map_sync"]

    assert (maps["held"], maps["kept_local"]) == ([], ["map_mine"])
    assert "map_team" in maps["adopted"]
    names = {token: json.loads(MapStore().read(token))["name"] for token in ("map_same", "map_mine", "map_team")}
    assert names == {"map_same": "Same", "map_mine": "Mine v2, edited while local", "map_team": "Team v2, edited by the team"}
    assert not (runtime_paths.realm_sync_root() / realm.id / "map_conflicts").exists()


def test_a_leave_notice_replayed_after_a_rejoin_leaves_the_fresh_realm_bound(tmp_path, monkeypatch):
    """RT-REVOKED-REPLAYED-AFTER-A-REJOIN-TURNS-THE-FRESH-REALM-LOCAL. After a re-join the team's realm id names the
    fresh bound realm again, so the first ``realm.revoked`` arriving again (Eternia's personal-channel replay) read
    as a second leave and turned the fresh realm into a second local copy. A notice carrying ``occurred_at``
    older than this install's binding of the realm now changes nothing (``stale``); a leave after the re-join is
    taken; a time that is not ISO 8601 is refused.

    Mutation: drop the ``occurred_at >= bound_at`` comparison in ``realm_verbs._older_than_binding`` (always take
    the notice) -> the replay converts the fresh realm, ``stale`` false, red (recorded in the commit)."""
    from datetime import UTC, datetime

    realm = RealmStore().create(name="Team", server_id="srv_team", realm_id="realm_team")
    WorkspaceStore().create(name="Shared", realm_id=realm.id, workspace_id="ws_shared")
    left_at = datetime.now(UTC).isoformat()
    first = _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_left", occurred_at=left_at)["result"]
    assert (first["became_local"], first["rekey"], first["stale"]) == (True, "done", False)
    local_copy = first["rekeyed_to"]
    _join(monkeypatch, tmp_path)
    assert RealmStore().get(realm.id).server_id == "srv_team"

    replay = _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_left", occurred_at=left_at)["result"]

    assert (replay["became_local"], replay["stale"], replay["shared_from"]) == (False, True, None)
    assert RealmStore().get(realm.id).server_id == "srv_team"
    assert sorted(item.id for item in RealmStore().list_all(include_archived=True)) == sorted([realm.id, local_copy])
    assert read_rekey_journal(realm.id)["map"]["realm_new"] == local_copy

    refused = _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_left", occurred_at="yesterday")
    assert refused["error"]["data"]["reason"] == "invalid_request"
    assert RealmStore().get(realm.id).server_id == "srv_team"

    again = _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_left",
                 occurred_at=datetime.now(UTC).isoformat())["result"]
    assert (again["became_local"], again["stale"]) == (True, False)
    assert RealmStore().get(again["rekeyed_to"]).server_id is None
