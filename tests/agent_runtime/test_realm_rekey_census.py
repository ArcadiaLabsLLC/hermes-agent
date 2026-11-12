"""The owned re-key of a realm that turned local (``agent_runtime.realm_rekey``,
RT-REKEY-ONE-OWNED-OPERATION; plan ``docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md``).

The realm is seeded through the real stores, published to a bare team repository, left through
``runtime.realm.revoked``, edited and synced while local (a re-key test without a sync run made while local
proved nothing for lane hm-leftrealm), then re-keyed. The census reads every file name and every file's content
under the store root. Killing mutations are named per test."""
import inspect
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_runtime import paths as runtime_paths
from agent_runtime import realm_rekey, serve_rpc
from agent_runtime.agent_create import perform_agent_create
from agent_runtime.board_models import default_board_id
from agent_runtime.board_store import BoardStore
from agent_runtime.flow_graph import FlowGraphStore, parse_flow_graph_doc
from agent_runtime.models import AgentPersona
from agent_runtime.office_store import OfficeStore
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.realm_rekey_agents import parked_agents_dir, restore_parked_agents
from agent_runtime.realm_rekey import PlaceClass, RekeyState, leftover_ids, owe_rekey, place_class, rekey_realm
from agent_runtime.realm_sync import RealmSyncError, publish_realm_sync, pull_realm_sync
from agent_runtime.realm_sync.revocation import read_realm_shared_from
from agent_runtime.store import AgentStore, RealmStore, WorkspaceStore

#: Only the top-level ``sceneId`` is the level's address; the same text deeper in the document is the author's.
LEVEL = '{"version": 7,  "sceneId": "ws-%s", "props": [{"sceneId": "prop-ws-%s"}]}'


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _left_realm(tmp_path):
    """A server realm of two workspaces, published, left, then changed and synced while local."""
    bare, clone = tmp_path / "team.git", tmp_path / "team-clone"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "member@localhost")
    _git(clone, "config", "user.name", "Member")
    _git(clone, "commit", "--allow-empty", "-m", "init")
    _git(clone, "remote", "add", "origin", str(bare))
    _git(clone, "push", "-q", "-u", "origin", "HEAD")
    realm = RealmStore().create(name="Team", server_id="srv_team", realm_id="realm_team")
    realm.sync_manifest_ref = str(clone)
    realm = RealmStore().save(realm)
    first = WorkspaceStore().create(name="Shared", realm_id=realm.id, workspace_id="ws_shared")
    second = WorkspaceStore().create(name="Second", realm_id=realm.id)
    realm = RealmStore().get(realm.id)
    realm.workspace_ids, realm.default_workspace_id = [first.id, second.id], first.id
    realm = RealmStore().save(realm)
    boards = BoardStore()
    boards.add_card(workspace_id=first.id, title="Team card")
    extra = boards.create(workspace_id=second.id, title="Extra board")
    boards.add_card(workspace_id=second.id, title="On the extra board", board_id=extra.board_id)
    _seat_two_agents(first.id, realm.id)
    level = runtime_paths.level_path(first.id)
    level.parent.mkdir(parents=True, exist_ok=True)
    level.write_text(LEVEL % (first.id, first.id), encoding="utf-8")
    WorkspaceStore().set_active(first.id)
    assert publish_realm_sync(realm.id)["changed"] is True
    left = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "rk", "method": "runtime.realm.revoked",
                                     "params": {"realm_id": realm.id, "reason": "membership_left"}})
    assert left["result"]["became_local"] is True
    boards.add_card(workspace_id=first.id, title="Added while local")
    try:  # a local realm's own sync run: it rewrites the baselines the re-key must carry over
        publish_realm_sync(realm.id)
        pull_realm_sync(realm.id)
    except RealmSyncError:
        pass
    # A neighbour in another realm whose ids only START with ours: never touched.
    other = RealmStore().create(name="Mine", realm_id="realm_team_2")
    neighbour = WorkspaceStore().create(name="Neighbour", realm_id=other.id, workspace_id="ws_shared_2")
    boards.add_card(workspace_id=neighbour.id, title="Neighbour card")
    return realm, first, second, extra, _git(bare, "rev-parse", "main")


LEAD, HELPER = "personainst_qa_agent_1", "personainst_qa_agent_0a1b2c3d"


def _seat_two_agents(workspace_id: str, realm_id: str) -> None:
    """Two team agents at desks through the create door (row, chat root, desk), the second steered by the
    first; the first owns a flow graph that draws the second, and a schedule names it."""
    AgentStore().save(AgentPersona(id="qa", display_name="QA Agent", role="qa", model=None, provider=None,
                                   api_mode=None, system_prompt_path=""))
    OfficeStore().ensure_surface(workspace_id, created_by="seed")
    for index, agent in enumerate((LEAD, HELPER)):
        made = perform_agent_create({"persona_id": "qa", "workspace_id": workspace_id, "realm_id": realm_id,
                                     "position": [float(index), 1.0], "idempotency_key": f"seat-{index}",
                                     "placement_id": agent.removeprefix("personainst_")})
        assert made.refusal is None and made.result["persona_instance_id"] == agent
    PersonaInstanceStore().patch_fields(HELPER, steered_by=[LEAD])
    FlowGraphStore().set_doc(parse_flow_graph_doc({
        "graph_id": f"runtime:{LEAD}", "edges": [{"from": "n1", "to": "n2"}],
        "nodes": [{"id": "n1", "agent": LEAD}, {"id": "n2", "agent": HELPER}]}))
    schedule = runtime_paths.store_root() / "schedules" / "sched_nightly.json"
    schedule.parent.mkdir(parents=True, exist_ok=True)
    schedule.write_text(json.dumps({"key": "sched_nightly", "workspace_id": workspace_id,
                                    "action": {"kind": "prompt", "persona_instance_id": LEAD}}), encoding="utf-8")


def _session_ids() -> set[str]:
    db = default_persona_session_db()
    try:
        return {row[0] for row in db._conn.execute("SELECT id FROM sessions").fetchall()}
    finally:
        db.close()


def _titles(workspace_id: str) -> dict[str, list[str]]:
    boards = BoardStore()
    found = {}
    for definition in sorted(runtime_paths.boards_root().glob("*/board.json")):
        board = json.loads(definition.read_text(encoding="utf-8"))
        if board["workspace_id"] == workspace_id:
            found[board["board_id"]] = sorted(card.title for card in boards.list_cards(board["board_id"]))
    return found


def _assert_local_copy_is_whole(journal, first, second, extra) -> None:
    mapping = journal["map"]
    new_first, new_second = mapping["workspaces"][first.id], mapping["workspaces"][second.id]
    realm = RealmStore().get(mapping["realm_new"])
    assert (realm.workspace_ids, realm.default_workspace_id) == ([new_first, new_second], new_first)
    assert (realm.server_id, realm.deleted_workspace_ids) == (None, [])
    assert [item.id for item in RealmStore().list_all(include_archived=True)].count("realm_team") == 0
    assert {WorkspaceStore().get(item).realm_id for item in (new_first, new_second)} == {realm.id}
    assert _titles(new_first) == {default_board_id(new_first): ["Added while local", "Team card"]}
    assert _titles(new_second)[mapping["boards"][extra.board_id]] == ["On the extra board"]
    assert not _titles(first.id) and not _titles(second.id)
    assert WorkspaceStore().active_id() == new_first
    assert read_realm_shared_from(realm.id)["server_id"] == "srv_team"
    assert runtime_paths.level_path(new_first).read_text(encoding="utf-8") == LEVEL % (new_first, first.id)
    assert not runtime_paths.level_path(first.id).exists()
    # The neighbour whose ids start with ours is exactly as it was.
    assert WorkspaceStore().get("ws_shared_2").realm_id == "realm_team_2"
    assert _titles("ws_shared_2") == {default_board_id("ws_shared_2"): ["Neighbour card"]}
    assert RealmStore().get("realm_team_2").id == "realm_team_2"


def _census(journal) -> dict[str, list[dict]]:
    forms = realm_rekey.RekeyMap(**journal["map"]).forms()
    by_class: dict[str, list[dict]] = {}
    for row in leftover_ids(runtime_paths.store_root(), list(forms)):
        by_class.setdefault(row["class"], []).append(row)
    return by_class


def test_a_left_realm_is_rekeyed_whole_and_no_old_id_stays_where_the_local_copy_lives(tmp_path):
    """Mutations: drop ``_step_rename`` from STEPS -> the stores cannot load the new ids and the census names
    ``workspaces/ws_shared.json``, red; drop ``_step_content`` -> ``realm_id`` inside the workspace files, red;
    rewrite by text search (``value.replace(old, new)``) -> the neighbour ``ws_shared_2`` is re-keyed, red; drop
    the ``sceneId`` patch -> the level assert, red; json-rewrite a level -> its bytes change, red; drop
    ``_step_ledgers`` on a realm whose ledger holds an id -> covered by the ledger test below."""
    realm, first, second, extra, team_head = _left_realm(tmp_path)
    before = _census({"map": {"realm_old": realm.id, "realm_new": "x", "workspaces": {first.id: "y", second.id: "z"},
                              "boards": {}, "agents": {}}})
    assert before.get("moves"), "the seed holds the old ids where the local copy lives"

    owed = owe_rekey(realm.id, reason="membership_left")
    assert owed["state"] == RekeyState.OWED.value and owe_rekey(realm.id, reason="again") == owed
    assert set(owed["map"]["workspaces"]) == {first.id, second.id}
    assert set(owed["map"]["boards"]) == {default_board_id(first.id), default_board_id(second.id), extra.board_id}
    assert RealmStore().get(realm.id).workspace_ids == [first.id, second.id]  # owing moves nothing

    journal = rekey_realm(realm.id)

    assert (journal["state"], journal["steps_done"], journal["leftover"]) == (
        RekeyState.DONE.value, ["agents", "content", "rename", "ledgers"], [])
    _assert_local_copy_is_whole(journal, first, second, extra)
    census = _census(journal)
    assert census.get("moves", []) == [] and census.get("unclassified", []) == []
    # The journal (history) is the one place that must still name the old ids: it is the map.
    assert {row["path"] for row in census["history"]} >= {f"{realm_rekey.JOURNAL_DIRNAME}/realm_team.json"}
    assert _git(tmp_path / "team.git", "rev-parse", "main") == team_head
    assert rekey_realm(realm.id) == journal  # a done re-key is answered, not run again


@pytest.mark.parametrize("killed_after", ["agents", "first park", "content", "rename", "first rename"])
def test_a_rekey_killed_part_way_is_finished_by_running_it_again(tmp_path, monkeypatch, killed_after):
    """Mutations: mint the map inside ``rekey_realm`` instead of reading the journal -> the second run renames
    to other ids and the local copy is split, red; drop the folder merge in ``_step_rename`` -> the card a late
    writer put under the old board id stays there and the census names it, red; read an agent only from
    ``persona_instances/`` (drop the parked fallback in ``step_agents``) -> the agent parked before the kill
    never gets its steering edge, red."""
    realm, first, second, extra, _ = _left_realm(tmp_path)
    owed = owe_rekey(realm.id, reason="membership_left")

    class Killed(RuntimeError):
        pass

    if killed_after == "first rename":
        real, calls = Path.rename, []

        def rename_once(self, target):
            if calls:
                raise Killed()
            calls.append(self)
            return real(self, target)

        monkeypatch.setattr(Path, "rename", rename_once)
    elif killed_after == "first park":
        from agent_runtime import realm_rekey_agents

        real_move = shutil.move

        def park_then_die(source, target):
            real_move(source, target)
            raise Killed()

        monkeypatch.setattr(realm_rekey_agents.shutil, "move", park_then_die, raising=True)
    else:
        steps = dict(realm_rekey.STEPS)

        def then_die(root, mapping):
            steps[killed_after](root, mapping)
            raise Killed()

        monkeypatch.setattr(realm_rekey, "STEPS", tuple(
            (name, then_die if name == killed_after else step) for name, step in realm_rekey.STEPS))
    with pytest.raises(Killed):
        rekey_realm(realm.id)
    assert realm_rekey.read_rekey_journal(realm.id)["state"] == RekeyState.RUNNING.value
    monkeypatch.undo()
    minted = {item.id: item.default_chat_session_id for item in PersonaInstanceStore().list_all()
              if item.id in owed["map"]["agents"].values()}
    if killed_after == "rename":  # a writer that still held the old id re-made the old board folder
        late = runtime_paths.board_card_path(default_board_id(first.id), "card_late")
        late.parent.mkdir(parents=True)
        moved = runtime_paths.board_cards_dir(owed["map"]["boards"][default_board_id(first.id)])
        new_board = moved.parent.name
        late.write_text(next(moved.glob("*.json")).read_text(encoding="utf-8").replace(
            new_board, default_board_id(first.id)), encoding="utf-8")

    journal = rekey_realm(realm.id)

    if killed_after == "rename":
        assert json.loads((moved / "card_late.json").read_text(encoding="utf-8"))["board_id"] == new_board
        assert not late.parent.parent.exists()
        (moved / "card_late.json").unlink()

    assert journal["map"] == owed["map"] and journal["leftover"] == []
    agents = {item.id: item.default_chat_session_id for item in PersonaInstanceStore().list_all() if "_agent_" in item.id}
    assert set(agents) == set(owed["map"]["agents"].values()) and minted.items() <= agents.items()
    assert sorted(path.stem for path in parked_agents_dir(realm.id).glob("*.json")) == sorted(owed["map"]["agents"])
    assert PersonaInstanceStore().get(owed["map"]["agents"][HELPER]).steered_by == [owed["map"]["agents"][LEAD]]
    _assert_local_copy_is_whole(journal, first, second, extra)
    assert _census(journal).get("moves", []) == []


def test_the_local_copy_starts_with_a_clean_delete_ledger(tmp_path):
    """Mutation: drop ``_step_ledgers`` from STEPS -> the new realm still lists ``ws_gone``, red."""
    realm = RealmStore().create(name="Team", realm_id="realm_team")
    WorkspaceStore().create(name="Shared", realm_id=realm.id, workspace_id="ws_shared")
    realm = RealmStore().get(realm.id)
    realm.deleted_workspace_ids = ["ws_gone"]
    RealmStore().save(realm)

    journal = rekey_realm(owe_rekey(realm.id, reason="membership_left")["map"]["realm_old"])

    assert RealmStore().get(journal["map"]["realm_new"]).deleted_workspace_ids == []


def test_every_id_keyed_path_of_the_store_is_in_exactly_one_class():
    """A new ``paths.py`` function that takes a realm, workspace, board or agent id must land in a classified
    top-level entry. Mutation: drop ``"levels"`` (or any entry) from STORE_PLACES -> named here, red."""
    keyed = {"workspace_id", "realm_id", "board_id", "persona_instance_id", "instance_id"}
    root = runtime_paths.store_root()
    unclassified, seen = [], 0
    for name, function in inspect.getmembers(runtime_paths, inspect.isfunction):
        parameters = inspect.signature(function).parameters
        required = [p for p in parameters.values() if p.default is inspect.Parameter.empty
                    and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
        if function.__module__ != runtime_paths.__name__ or not keyed & set(parameters):
            continue
        result = function(**{p.name: f"probe_{p.name}" for p in required})
        try:
            relative = Path(result).relative_to(root)
        except ValueError:
            continue  # not under the store root (a chat folder under a profile home): never re-keyed
        seen += 1
        if place_class(relative) is None:
            unclassified.append(f"{name} -> {relative.as_posix()}")
    assert seen >= 40, "the probe stopped finding the id-keyed path functions"
    assert unclassified == []
    assert {place_class(Path("work/workspace_chats_ws_x/a.db")), place_class(Path("workspace_chats/ws_x.db"))} == {
        PlaceClass.PARKS}
    assert place_class(Path("work/ws_x/brain/.git/HEAD")) is PlaceClass.HISTORY


def test_the_local_copy_gets_new_agents_at_the_same_desks_and_the_teams_agents_wait_with_their_chats(tmp_path):
    """RT-REKEY-LOCAL-COPY-GETS-NEW-AGENTS. Mutations: drop ``step_agents`` from STEPS -> no new agent and the
    team's rows are still live, red; leave ``agents`` out of ``RekeyMap.forms`` -> the desk, the flow graph and
    the schedule still name the team's agent, red; retire instead of park (``store.retire_replica``) -> nothing
    under ``persona_instances_parked`` and the restore returns nothing, red; mint with the team's
    ``default_chat_session_id`` -> the new agent opens the team's chat, red; skip
    ``apply_replicated_steering`` -> the new helper has no parent, red; drop the canonical-channel test in
    ``agents_of`` -> ``personainst_qa`` parks, red."""
    realm, first, second, extra, _ = _left_realm(tmp_path)
    store = PersonaInstanceStore()
    channel = store.ensure_for_persona(AgentStore().get("qa"))
    team = {agent: store.get(agent) for agent in (LEAD, HELPER)}
    team_chats = {item.default_chat_session_id for item in team.values()}
    assert team_chats <= _session_ids() and None not in team_chats

    journal = rekey_realm(owe_rekey(realm.id, reason="membership_left")["map"]["realm_old"])

    agents, new_first = journal["map"]["agents"], journal["map"]["workspaces"][first.id]
    assert set(agents) == {LEAD, HELPER} and not set(agents.values()) & set(agents)
    live = {item.id: item for item in store.list_all()}
    assert channel.id in live and not {LEAD, HELPER} & set(live)
    for old, new in agents.items():
        mine = live[new]
        assert (mine.persona_id, mine.display_name, mine.workspace_id, mine.realm_id) == (
            "qa", team[old].display_name, new_first, journal["map"]["realm_new"])
        assert mine.default_chat_session_id not in team_chats and new in mine.default_chat_session_id
        assert (mine.active_run_id, mine.state.value) == (None, "idle")
    assert live[agents[HELPER]].steered_by == [agents[LEAD]]
    # The desks, the canvas and the schedule of the local copy name the new agents.
    desks = {actor.actor_key: actor for actor in OfficeStore().scan_actors(new_first).actors}
    assert set(desks) == set(agents.values())
    assert {(desk.persona_instance_id, desk.items[0].item_id) for desk in desks.values()} == {
        (new, new) for new in agents.values()}
    assert not runtime_paths.office_dir(first.id).exists()
    graphs = FlowGraphStore()
    assert graphs.list_ids() == [f"runtime_{agents[LEAD]}"]
    assert [node["agent"] for node in graphs.get(f"runtime_{agents[LEAD]}")["doc"]["nodes"]] == [agents[LEAD], agents[HELPER]]
    schedule = json.loads((runtime_paths.store_root() / "schedules" / "sched_nightly.json").read_text(encoding="utf-8"))
    assert (schedule["workspace_id"], schedule["action"]["persona_instance_id"]) == (new_first, agents[LEAD])
    census = _census(journal)
    assert census.get("moves", []) == [] and census.get("unclassified", []) == []
    # The team's agents wait whole, and nothing that runs at a serve start or in a reconcile takes their chats.
    parked = parked_agents_dir(realm.id)
    assert sorted(path.stem for path in parked.glob("*.json")) == sorted(agents)
    _run_every_sweep_a_serve_start_and_a_reconcile_run()
    assert team_chats <= _session_ids()
    assert sorted(path.stem for path in parked.glob("*.json")) == sorted(agents)
    assert set(agents.values()) <= {item.id for item in store.list_all()}

    assert sorted(restore_parked_agents(realm.id)) == sorted(agents) and restore_parked_agents(realm.id) == []
    assert not parked.exists()
    for old, was in team.items():
        back = store.get(old)
        assert (back.default_chat_session_id, back.workspace_id, back.realm_id, back.steered_by) == (
            was.default_chat_session_id, first.id, realm.id, was.steered_by)


def _run_every_sweep_a_serve_start_and_a_reconcile_run() -> None:
    """Plan §10: does any sweep delete parked data whose workspace or agent is absent? The boot sweeps
    (``boot_phases._run_boot_sweeps``), the chat-receipt repair and the persona-instance reconcile, for real."""
    from agent_runtime.chat_turn_reservations import repair_orphaned_chat_receipts
    from agent_runtime.persona_chat_continuity import repair_orphaned_chat_turns
    from agent_runtime.persona_instance_identity import reconcile_persona_instances
    from agent_runtime.project_migration import migrate_namespace

    repair_orphaned_chat_turns()
    repair_orphaned_chat_receipts()
    PersonaInstanceStore().retire_task_bound_rows(apply=True)
    migrate_namespace()
    reconcile_persona_instances(apply=True)
