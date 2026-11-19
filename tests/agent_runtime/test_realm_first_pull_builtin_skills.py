"""A member's first pull does not leave the built-in agent skills reading as his to push.

RT-FIRST-PULL-INSTALLS-SKILLS-THAT-READ-AS-YOURS-TO-PUSH: a pull (and every serve boot) installs the
shipped harness skills into the machine's shared skills root. When the realm does not carry them — its
publisher's hermes predates one of them, or published before any boot — the member's status listed
each as a skill ``added`` and ``unpublished_changes: true`` with ``publish_changes`` empty (seen
2026-11-18 on a scratch root through the real CLI). A shipped copy, byte-equal to this hermes's
source, is not the member's change; an edited one still is.

Pinned through the app's door, ``runtime.realm.sync.status``. Killing mutations are named per test.
"""
from __future__ import annotations

import pytest

from agent_runtime import serve_rpc
from agent_runtime.profile_home import get_shared_skills_dir
from agent_runtime.realm_sync import publish_realm_sync
from agent_runtime.skill_install import HARNESS_SKILLS
from agent_runtime.store import WorkspaceStore
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team


@pytest.fixture
def realm(tmp_path, monkeypatch):
    team = _Team(tmp_path, monkeypatch)  # one Hermes home per member
    shared = team.found("alice", "Team Realm", "srv_team")
    WorkspaceStore().create(name="Roadmap", realm_id=shared.id)
    publish_realm_sync(shared.id)  # Alice's root holds no harness skill: the realm carries none
    team.join("bob", shared)  # Bob's first pull installs them
    return shared


def _status(realm_id: str) -> dict:
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": "runtime.realm.sync.status",
                                      "params": {"realm_id": realm_id}})
    assert "error" not in reply, reply
    return reply["result"]


def _skill_rows(status: dict) -> list[tuple[str, str]]:
    return sorted((i["item_key"], i["kind"]) for i in status["store_drift"]["items"] if i["family"] == "skill")


def test_a_first_pull_s_shipped_skills_read_as_nothing_to_push(realm):
    """Mutation: drop the shipped-copy skip in ``_skill_store_drift_items``'s ``added`` arm -> the four
    harness skills read ``added`` and ``unpublished_changes`` is true, red."""
    assert {p.name for p in get_shared_skills_dir().iterdir() if p.name in HARNESS_SKILLS} == set(HARNESS_SKILLS)
    status = _status(realm.id)
    assert _skill_rows(status) == []
    assert status["unpublished_changes"] is False


def test_an_edited_built_in_skill_still_reads_as_the_members_change(realm):
    """Mutation: skip every harness slug whatever its content -> the edit reads as nothing, red."""
    slug = sorted(HARNESS_SKILLS)[0]
    skill = get_shared_skills_dir() / slug / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nMy own rule.\n", encoding="utf-8")
    assert _skill_rows(_status(realm.id)) == [(slug, "added")]
