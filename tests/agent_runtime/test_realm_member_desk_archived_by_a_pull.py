"""A teammate deletes a shared agent and brings it back: a member gets it back, and only pulling never
reads as an unpublished change.

RT-REALM-MEMBER-DESK-ARCHIVED-BY-A-PULL-BLOCKS-THE-AGENT-COMING-BACK, seen live 2026-11-19 (w1118a-realm3):
owner B deleted an agent and published; member A pulled and read "Unpublished changes" ("CANVASES NO
LONGER PUBLISHED: runtime_<agent>") though A changed nothing; B's realm was put back to the earlier tree,
A pulled again, and the agent did not come back ("you archived their desks on this machine").

Reproduced here before the fix on two simulated computers (``_Team``), the same steps: after the delete's
pull the canvas baseline still named a canvas neither side publishes any more (a ``removed`` row), and
after the restore's pull the office pull answered ``conflicts: 1`` (``archive_vs_edit``), no desk, no
agent, and the surface read changed — the pull had entered the teammate's delete in the member's ledger
as the member's own. The fix: the office ledger records who archived each desk (this machine, or the
realm: ``office_store.files.read_realm_held``), only this machine's own archives are
``locally_archived``, and a canvas neither side publishes leaves the canvas baseline. The restore is done
the way the live read did it: the realm's git tree put back to the commit before the delete.
Killing mutations are named per test.
"""
from __future__ import annotations

import subprocess

import pytest

from agent_runtime import serve_rpc
from agent_runtime.agent_create import perform_agent_create
from agent_runtime.agent_retire import perform_agent_retire
from agent_runtime.flow_graph import FlowGraphStore, parse_flow_graph_doc
from agent_runtime.models import AgentPersona
from agent_runtime.office_store import OfficeStore
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
from agent_runtime.store import AgentStore, WorkspaceStore
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team

AGENT = "personainst_qa_agent_1f933b64"


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _unpublished(realm_id: str) -> tuple[bool, list[tuple]]:
    """``(unpublished_changes, [(family, item, kind)])`` as the realm card reads them."""
    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "st", "method": "runtime.realm.sync.status", "params": {"realm_id": realm_id}})
    status = reply["result"]
    return status["unpublished_changes"], [
        (str(item["family"]), item["item_key"], item["kind"]) for item in status["store_drift"]["items"]]


def _agent_here(workspace_id: str) -> bool:
    desks = [actor.actor_key for actor in OfficeStore().scan_actors(workspace_id).actors]
    return desks == [AGENT] and any(row.id == AGENT for row in PersonaInstanceStore().scan_all().instances)


def _shared_agent(team: _Team):
    """Alice's realm: one workspace, one agent at a desk with its canvas, published; Bob joins and pulls."""
    shared = team.found("alice", "Team Realm", "srv_team")
    workspace = WorkspaceStore().create(name="Roadmap", realm_id=shared.id)
    # ``api_mode`` stated: a pulled persona that omits it resolves the member's own default and reads as
    # changed after any pull (a separate defect, RT-REALM-PULLED-PERSONA-WITHOUT-API-MODE-READS-CHANGED).
    AgentStore().save(AgentPersona(id="qa", display_name="QA Agent", role="qa", model=None, provider=None,
                                   api_mode="codex_responses", system_prompt_path=""))
    OfficeStore().ensure_surface(workspace.id, created_by="seed")
    made = perform_agent_create({"persona_id": "qa", "workspace_id": workspace.id, "realm_id": shared.id,
                                 "position": [1.0, 1.0], "idempotency_key": "seat",
                                 "placement_id": AGENT.removeprefix("personainst_")})
    assert made.refusal is None, made.refusal
    FlowGraphStore().set_doc(parse_flow_graph_doc(
        {"graph_id": f"runtime:{AGENT}", "edges": [], "nodes": [{"id": "n1", "agent": AGENT}]}))
    publish_realm_sync(shared.id)
    before_delete = _git(team.clone("alice", shared.server_id), "rev-parse", "HEAD")
    team.join("bob", shared)
    assert _agent_here(workspace.id)
    assert _unpublished(shared.id) == (False, [])
    return shared, workspace, before_delete


def _alice_deletes_and_publishes(team: _Team, shared) -> None:
    team.be("alice")
    assert perform_agent_retire({"persona_instance_id": AGENT}).result["archived_actor_keys"] == [AGENT]
    publish_realm_sync(shared.id)


def _alice_puts_the_realm_back(team: _Team, shared, commit: str) -> None:
    """The live read's restore: the realm's tree as it was at ``commit``, committed on top and pushed."""
    team.be("alice")
    clone = team.clone("alice", shared.server_id)
    _git(clone, "fetch", "-q", "origin")
    _git(clone, "reset", "-q", "--hard", "origin/main")
    _git(clone, "checkout", commit, "--", ".")
    _git(clone, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "-m", "restore the agent")
    _git(clone, "push", "-q", "origin", "HEAD:main")


def test_a_teammates_delete_then_restore_brings_the_agent_back_and_nothing_reads_unpublished(team):
    """Delete, pull, restore, pull — on the member's machine.

    Mutations: in ``office_sync._reconcile_actors``' archive arm record the tombstone again
    (``record_tombstone=True``) -> the restore's pull answers ``(0, 1)`` (a conflict), red; in
    ``apply_office_pull`` read ``local_surface.archived_actor_keys`` instead of ``own_archived_actor_keys``
    -> the same red; in ``adopt_remote_surface`` pass an empty set for the realm-held keys -> every key reads
    as Bob's own again and the agent stays gone, red at the second ``_agent_here``; in
    ``apply_flow_graph_pull`` skip
    ``_release_unshipped_baselines`` -> the delete's pull reads ``flow_graph ... removed``, red at the first
    ``_unpublished``."""
    shared, workspace, before_delete = _shared_agent(team)
    _alice_deletes_and_publishes(team, shared)

    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert pulled["office_sync"]["archived"] == 1
    assert not _agent_here(workspace.id)
    assert _unpublished(shared.id) == (False, [])

    _alice_puts_the_realm_back(team, shared, before_delete)
    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert (pulled["office_sync"]["adopted"], pulled["office_sync"]["conflicts"]) == (1, 0)
    assert _agent_here(workspace.id)
    assert _unpublished(shared.id) == (False, [])

    pull_realm_sync(shared.id)
    assert _agent_here(workspace.id)
    assert _unpublished(shared.id) == (False, [])


def test_a_desk_the_member_deleted_himself_stays_deleted_when_the_teammate_restores_it(team):
    """The hand archive wins: Bob deleted the agent on his machine, Alice deleted and then restored it.
    Bob's own delete is his own change, so it is still what Bob has after the restore's pull.

    Mutation: in ``merge_archived_ledgers_by_origin`` treat every local key as the realm's
    (``own = []``) -> the restore drops Bob's own tombstone and the agent comes back, red."""
    shared, workspace, before_delete = _shared_agent(team)
    team.be("bob")
    assert perform_agent_retire({"persona_instance_id": AGENT}).result["archived_actor_keys"] == [AGENT]
    _alice_deletes_and_publishes(team, shared)
    team.be("bob")
    pull_realm_sync(shared.id)
    assert not _agent_here(workspace.id)

    _alice_puts_the_realm_back(team, shared, before_delete)
    team.be("bob")
    pull_realm_sync(shared.id)
    assert not _agent_here(workspace.id)
    assert AGENT in OfficeStore().own_archived_actor_keys(workspace.id)
