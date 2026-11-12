"""Putting a realm away and bringing it back (``agent_runtime.realm_manage``, RT-REALM-ARCHIVE-RESTORE), and
the archived flag staying on this machine through realm sync. Killing mutations are named per test."""
import json
import subprocess
from types import SimpleNamespace

from agent_runtime import paths as runtime_paths
from agent_runtime import serve_rpc
from agent_runtime.realm_sync import pull_realm_sync
from agent_runtime.realm_sync.artifacts import _workspace_realm_artifacts
from agent_runtime.store import RealmStore, WorkspaceStore


def _rpc(method, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "m", "method": method, "params": params})


def _events(realm_id):
    return [(event.type, event.payload.get("change")) for event in RealmStore().event_log.tail(50)
            if event.payload.get("realm_id") == realm_id and event.type in ("realm.archived", "realm.updated")]


def test_an_empty_realm_is_archived_and_brought_back_and_each_repeat_writes_nothing():
    """Mutations: drop the ``realms.archive`` call -> ``archived`` stays false, red; report ``changed`` true on
    the repeat -> the second flag, red; drop ``RealmStore.unarchive``'s ``archived = False`` -> the realm stays
    archived, red; emit on the no-op -> the event list grows, red."""
    realms = RealmStore()
    home, spare = realms.create(name="Home"), realms.create(name="Spare")
    realms.set_active(home.id)
    first = _rpc("runtime.realm.archive", realm_id=spare.id)["result"]
    assert (first["id"], first["archived"], first["changed"], first["kind"]) == (spare.id, True, True, "realm")
    assert [item.id for item in realms.list_all()] == [home.id]
    again = _rpc("runtime.realm.archive", realm_id=spare.id)["result"]
    assert (again["archived"], again["changed"]) == (True, False)
    assert realms.active_id() == home.id
    back = _rpc("runtime.realm.unarchive", realm_id=spare.id)["result"]
    assert (back["id"], back["archived"], back["changed"]) == (spare.id, False, True)
    assert sorted(item.id for item in realms.list_all()) == sorted([home.id, spare.id])
    repeat = _rpc("runtime.realm.unarchive", realm_id=spare.id)["result"]
    assert (repeat["archived"], repeat["changed"]) == (False, False)
    assert _events(spare.id) == [("realm.archived", None), ("realm.updated", "unarchived")]


def test_a_realm_holding_a_live_workspace_is_refused_and_archived_workspaces_do_not_count():
    """Mutations: drop the not-empty refusal -> KeyError 'error', red; count archived workspaces as live -> the
    last archive is refused (KeyError 'result'), red; drop the realm-less ``workspace_ids`` arm -> the listed
    realm-less workspace does not block, red."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    home, spare = realms.create(name="Home"), realms.create(name="Spare")
    realms.set_active(home.id)
    live = workspaces.create(name="Live", realm_id=spare.id)
    old = workspaces.create(name="Old", realm_id=spare.id)
    workspaces.archive(old.id)
    error = _rpc("runtime.realm.archive", realm_id=spare.id)["error"]
    assert (error["code"], error["data"]) == (4090, {"reason": "realm_not_empty", "workspace_ids": [live.id]})
    assert realms.get(spare.id).archived is False
    workspaces.archive(live.id)
    loose = workspaces.create(name="Loose")
    stored = realms.get(spare.id)
    stored.workspace_ids.append(loose.id)
    realms.save(stored)
    assert _rpc("runtime.realm.archive", realm_id=spare.id)["error"]["data"] == {
        "reason": "realm_not_empty", "workspace_ids": [loose.id]}
    workspaces.archive(loose.id)
    assert _rpc("runtime.realm.archive", realm_id=spare.id)["result"]["archived"] is True
    # Its archived workspaces stay archived, and come back only after the realm does.
    assert _rpc("runtime.workspace.unarchive", workspace_id=old.id)["error"]["data"]["reason"] == "realm_archived"
    assert _rpc("runtime.realm.unarchive", realm_id=spare.id)["result"]["changed"] is True
    assert workspaces.get(old.id).archived is True
    assert _rpc("runtime.workspace.unarchive", workspace_id=old.id)["result"]["restored"] is True


def test_the_default_the_active_and_a_server_realm_are_refused_and_nothing_is_written():
    """Mutations: drop the default refusal, the active refusal or the server-bound refusal -> KeyError 'error'
    each, red; check the default before the active realm -> a realm that is both answers ``realm_is_default``,
    red; check emptiness before the server-bound rule -> a server realm with a workspace answers
    ``realm_not_empty``, red."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    default, active = realms.create(name="Default"), realms.create(name="Active")
    team = realms.create(name="Team", server_id="srv_1")
    empty_team = realms.create(name="Empty Team", server_id="srv_2")
    workspaces.create(name="Shared", realm_id=team.id)
    both = realms.create(name="Both")
    realms.set_active(both.id)  # no pointer yet: the active realm IS the resolved default
    assert _rpc("runtime.realm.archive", realm_id=both.id)["error"]["data"] == {"reason": "realm_is_active"}
    realms.set_default_pointer(default.id)
    realms.set_active(active.id)
    for params, data, code in (
        ({"realm_id": "realm_nowhere"}, {"reason": "realm_not_found"}, 4001),
        ({"realm_id": 7}, {"reason": "invalid_request"}, -32602),
        ({}, {"reason": "invalid_request"}, -32602),
        ({"realm_id": default.id, "yes": True}, {"reason": "invalid_request"}, -32602),
        ({"realm_id": default.id}, {"reason": "realm_is_default"}, 4090),
        ({"realm_id": active.id}, {"reason": "realm_is_active"}, 4090),
        ({"realm_id": team.id}, {"reason": "realm_server_bound", "server_id": "srv_1"}, 4090),
        ({"realm_id": empty_team.id}, {"reason": "realm_server_bound", "server_id": "srv_2"}, 4090),
    ):
        error = _rpc("runtime.realm.archive", **params)["error"]
        assert (error["data"], error["code"]) == (data, code)
    assert [item.archived for item in realms.list_all(include_archived=True)] == [False] * 5
    for params, data, code in (({"realm_id": "realm_nowhere"}, {"reason": "realm_not_found"}, 4001),
                               ({"realm_id": ""}, {"reason": "invalid_request"}, -32602),
                               ({}, {"reason": "invalid_request"}, -32602)):
        error = _rpc("runtime.realm.unarchive", **params)["error"]
        assert (error["data"], error["code"]) == (data, code)
    # The default moves on -> the old default is an ordinary empty realm.
    realms.set_default_pointer(active.id)
    assert _rpc("runtime.realm.archive", realm_id=default.id)["result"]["changed"] is True


def test_the_argv_verbs_reach_the_same_implementation(monkeypatch, capsys):
    """Mutation: point ``harness realm archive`` at ``unarchive_realm`` (or the reverse) -> the stored flag, red;
    drop the argv refusal render -> exit 0 on the active realm, red."""
    from hermes_cli.harness_parts import realm_commands

    realms = RealmStore()
    home, spare = realms.create(name="Home"), realms.create(name="Spare")
    realms.set_active(home.id)
    rows = []
    monkeypatch.setattr(realm_commands, "_print_stage42", lambda envelope, **_: rows.append(envelope))
    assert realm_commands._cmd_realm_archive(SimpleNamespace(realm_id=spare.id)) == 0
    assert realms.get(spare.id).archived is True
    assert realm_commands._cmd_realm_unarchive(SimpleNamespace(realm_id=spare.id)) == 0
    assert realms.get(spare.id).archived is False
    assert [(row["archived"], row["changed"]) for row in rows] == [(True, True), (False, True)]
    assert realm_commands._cmd_realm_archive(SimpleNamespace(realm_id=home.id)) != 0
    assert "realm_is_active" in capsys.readouterr().out
    assert realms.get(home.id).archived is False


def test_an_argv_refusal_names_what_is_in_the_way_as_the_method_lane_does(capsys):
    """RT-REALM-ARCHIVE-ARGV-REFUSAL-DROPS-DETAILS. Mutation: in ``emit_harness_error`` drop the
    ``_REFUSALS_WITH_DETAILS`` arm -> ``safe_details`` is ``{error_class}`` only, red on every case."""
    from hermes_cli.harness_parts import realm_commands, workspace_commands

    realms = RealmStore()
    home, spare = realms.create(name="Home"), realms.create(name="Spare")
    team = realms.create(name="Team", server_id="srv_team")
    realms.set_active(home.id)
    workspace = WorkspaceStore().create(name="Roadmap", realm_id=spare.id)
    shared = WorkspaceStore().create(name="Shared", realm_id=team.id)

    def refused(command, **args):
        capsys.readouterr()
        assert command(SimpleNamespace(**args)) != 0
        error = json.loads(capsys.readouterr().out)["error"]
        details = dict(error["safe_details"])
        details.pop("error_class")
        return error["code"], details

    for realm_id in (spare.id, team.id):
        data = _rpc("runtime.realm.archive", realm_id=realm_id)["error"]["data"]
        reason = data.pop("reason")
        assert refused(realm_commands._cmd_realm_archive, realm_id=realm_id) == (reason, data)
    assert refused(realm_commands._cmd_realm_archive, realm_id=spare.id) == (
        "realm_not_empty", {"workspace_ids": [workspace.id]})
    assert refused(realm_commands._cmd_realm_archive, realm_id=team.id) == ("realm_server_bound", {"server_id": "srv_team"})
    assert refused(workspace_commands._cmd_workspace_move_realm, workspace_id=shared.id, realm_id=home.id) == (
        "workspace_move_confirm_required", {"owner_realm_id": team.id, "owner_realm_name": "Team"})


# ── the archived flag never travels through realm sync ───────────────────────

def _synced_realm(tmp_path, name="Synced"):
    realm = RealmStore().create(name=name)
    repo = tmp_path / "realm-sync-repo"
    subprocess.run(["git", "-C", str(tmp_path), "init", "realm-sync-repo"], check=True, capture_output=True, text=True)
    realm.sync_manifest_ref = str(repo)
    return RealmStore().save(realm), repo


def _repo_record(repo, realm_id):
    token = runtime_paths.safe_path_token(realm_id)
    return repo / "realms" / realm_id / "store" / "realms" / f"{token}.json"


def _publish_record(repo, realm_id, **overrides):
    record = json.loads(runtime_paths.realm_path(realm_id).read_text(encoding="utf-8"))
    record.update(overrides)
    dest = _repo_record(repo, realm_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


def test_a_pull_never_archives_a_realm_here_and_never_brings_one_back(tmp_path):
    """Mutation: drop the ``merged["archived"] = local_archived`` line in ``_pulled_artifact_bytes`` -> the
    pulled record's flag is adopted both ways, red (each half)."""
    realm, repo = _synced_realm(tmp_path)
    _publish_record(repo, realm.id, archived=True, skill_selection=["theirs"])
    pull_realm_sync(realm.id)
    pulled = RealmStore().get(realm.id)
    assert (pulled.archived, pulled.skill_selection) == (False, ["theirs"])  # the rest of the record still lands

    RealmStore().archive(realm.id)
    _publish_record(repo, realm.id, archived=False, skill_selection=["theirs", "again"])
    pull_realm_sync(realm.id)
    pulled = RealmStore().get(realm.id)
    assert (pulled.archived, pulled.skill_selection) == (True, ["theirs", "again"])


def test_a_first_pull_of_a_record_published_archived_lands_it_live(tmp_path):
    """Mutation: restore the ``not artifact.destination.exists()`` early return -> a record another machine
    published archived arrives archived here, red."""
    realm, repo = _synced_realm(tmp_path)
    _publish_record(repo, realm.id, archived=True)
    stored = runtime_paths.realm_path(realm.id)
    artifact = SimpleNamespace(kind="realm", source=_repo_record(repo, realm.id), destination=stored.with_name("absent.json"))
    from agent_runtime.realm_sync.pull import _pulled_artifact_bytes

    assert json.loads(_pulled_artifact_bytes(artifact, realm=realm))["archived"] is False


def test_a_publish_never_carries_the_archived_flag(tmp_path):
    """Mutation: drop ``content=_published_realm_record(realm)`` -> an archived realm publishes its file
    verbatim, ``archived: true``, red. A live realm still publishes its file byte for byte."""
    realm, _repo = _synced_realm(tmp_path)
    live = _workspace_realm_artifacts(realm, [])[0]
    assert live.content is None and live.read_bytes() == runtime_paths.realm_path(realm.id).read_bytes()
    archived = RealmStore().archive(realm.id)
    published = json.loads(_workspace_realm_artifacts(archived, [])[0].read_bytes())
    assert published["archived"] is False
    stored = json.loads(runtime_paths.realm_path(realm.id).read_text(encoding="utf-8"))
    assert stored["archived"] is True and {**stored, "archived": False} == published
