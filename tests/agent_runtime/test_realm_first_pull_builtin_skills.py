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
from agent_runtime.store import RealmStore, WorkspaceStore
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


# --- a hermes update (RT-FU-A-HERMES-UPDATE-MAKES-EVERY-REALM-ASK-TO-PUBLISH-ITS-BUILT-IN-SKILL) ---------------
#
# Review w1118a.63 D5 (a): the build owns a built-in skill's text. Seen live 2026-11-20 on account B: the team
# carried one harness skill as an older hermes shipped it, the member's newer hermes reinstalled its own on boot,
# and the status read that skill ``changed`` (``unpublished_changes: true``, ``publish_changes`` empty) after
# every pull. A harness skill equal to this install's shipped copy is never drift, whichever side is newer, and
# never published; a member's own edit still reads changed and ships.

_UPDATED = "harness-runtime-model"


def _variant_source(tmp_path, monkeypatch):
    """Point this hermes's shipped harness skills at a copy whose ``_UPDATED`` differs: a different version."""
    import shutil

    from agent_runtime import skill_install

    real = skill_install.harness_skill_source_root()
    variant = tmp_path / "other-hermes-harness-skills"
    shutil.copytree(real, variant)
    skill = variant / _UPDATED / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nA line another hermes version ships.\n", encoding="utf-8")
    monkeypatch.setattr(skill_install, "harness_skill_source_root", lambda: variant)


def _team_copy(realm) -> str | None:
    from agent_runtime import paths
    from tests.agent_runtime.test_workspace_move_out_of_server_realm import _git

    remote = realm.sync_manifest_ref  # Bob's clone; fetch what the remote holds
    _git(remote, "fetch", "-q", "origin")
    path = f"origin/main:realms/{paths.safe_path_token(realm.id)}/skills/{_UPDATED}/SKILL.md"
    try:
        return _git(remote, "show", path)
    except Exception:
        return None


@pytest.fixture(params=["team-older", "team-newer"])
def updated(request, tmp_path, monkeypatch):
    """Bob's realm whose team copy of ``_UPDATED`` is another hermes version's text, and Bob's root holding his
    own shipped copy. ``team-older``: the team copy came from an older hermes; ``team-newer``: from a newer one."""
    from agent_runtime import skill_install
    from agent_runtime.realm_sync import pull_realm_sync

    team = _Team(tmp_path, monkeypatch)
    shared = team.found("alice", "Team Realm", "srv_team")
    WorkspaceStore().create(name="Roadmap", realm_id=shared.id)
    publish_realm_sync(shared.id)
    real_root = skill_install.harness_skill_source_root
    if request.param == "team-older":
        _variant_source(tmp_path, monkeypatch)
    team.join("bob", shared)
    # The team copy was published by a hermes from before the rule, which shipped its own text.
    real_hash = skill_install.shipped_harness_skill_sync_hash
    monkeypatch.setattr(skill_install, "shipped_harness_skill_sync_hash", lambda slug: None)
    publish_realm_sync(shared.id)
    monkeypatch.setattr(skill_install, "shipped_harness_skill_sync_hash", real_hash)
    # Bob's hermes is now another version than the one that published.
    if request.param == "team-newer":
        _variant_source(tmp_path, monkeypatch)
    else:
        monkeypatch.setattr(skill_install, "harness_skill_source_root", real_root)
    pull_realm_sync(shared.id)  # the pull reinstalls this hermes's shipped skills, as every boot does
    team_text = _team_copy(RealmStore().get(shared.id))
    local_text = (get_shared_skills_dir() / _UPDATED / "SKILL.md").read_text(encoding="utf-8")
    assert team_text is not None and team_text != local_text  # the two versions really differ
    return RealmStore().get(shared.id), team_text


def test_a_hermes_update_s_built_in_skill_reads_as_nothing_to_push(updated):
    """Mutation: drop the shipped test from ``_skill_store_drift_items``'s ``changed`` arm -> ``_UPDATED`` reads
    ``changed`` and ``unpublished_changes`` is true, red (team-older and team-newer)."""
    realm, _team_text = updated
    status = _status(realm.id)
    assert _skill_rows(status) == []
    assert status["unpublished_changes"] is False


def test_a_publish_never_ships_this_installs_built_in_skill_text(updated):
    """Mutation: ``_published_skill_package`` returns the local package always -> the team copy becomes this
    hermes's text, red; and the status after it still reads nothing."""
    realm, team_text = updated
    publish_realm_sync(realm.id)
    assert _team_copy(realm) == team_text
    assert _skill_rows(_status(realm.id)) == []


def test_an_edited_built_in_skill_still_reads_changed_and_ships(updated):
    """Mutation: skip every harness slug in the ``changed`` arm whatever its content -> the edit reads as
    nothing, red."""
    realm, _team_text = updated
    skill = get_shared_skills_dir() / _UPDATED / "SKILL.md"
    edited = skill.read_text(encoding="utf-8") + "\nMy own rule.\n"
    skill.write_text(edited, encoding="utf-8")
    assert _skill_rows(_status(realm.id)) == [(_UPDATED, "changed")]
    publish_realm_sync(realm.id)
    assert _team_copy(realm) == edited.strip()  # ``_git`` strips its output


# --- a pull (RT-FU-A-BUILT-IN-SKILL-THE-TEAM-CARRIES-AT-ANOTHER-HERMES-VERSION-IS-HELD-ON-PULL) -------------------
#
# Review w1118a.64 D10 (a): D5's rule carried to the pull. Seen live 2026-11-20 (w1118a-hrt4, "HRT4 Realm"): the
# team carried ``harness-runtime-model`` as another hermes shipped it, this member's root held this hermes's
# shipped copy with no baseline entry, and ``realm sync pull`` answered ``skill_sync.held`` with it — a SKILLS
# HELD card for a skill the member never edited. A local copy equal to this install's shipped one is neither held
# nor adopted, whichever side is newer; a member's own edit meeting a changed team copy still holds.


def _held(realm_id: str) -> list[str]:
    from agent_runtime.realm_sync import pull_realm_sync

    return list(pull_realm_sync(realm_id)["skill_sync"]["held"])


@pytest.fixture(params=["team-older", "team-newer"])
def joined(request, tmp_path, monkeypatch):
    """Bob joins a realm whose team copy of ``_UPDATED`` is another hermes version's text, with no baseline for it.
    ``team-older``: Alice's hermes shipped the other text; ``team-newer``: Bob's does."""
    from agent_runtime import skill_install

    team = _Team(tmp_path, monkeypatch)
    shared = team.found("alice", "Team Realm", "srv_team")
    WorkspaceStore().create(name="Roadmap", realm_id=shared.id)
    real_root = skill_install.harness_skill_source_root
    if request.param == "team-older":
        _variant_source(tmp_path, monkeypatch)
    skill_install.install_harness_skills(skills=[_UPDATED])
    # Alice's hermes predates the publish rule, so the team carries her shipped text.
    real_hash = skill_install.shipped_harness_skill_sync_hash
    monkeypatch.setattr(skill_install, "shipped_harness_skill_sync_hash", lambda slug: None)
    publish_realm_sync(shared.id)
    monkeypatch.setattr(skill_install, "shipped_harness_skill_sync_hash", real_hash)
    if request.param == "team-newer":
        _variant_source(tmp_path, monkeypatch)
    else:
        monkeypatch.setattr(skill_install, "harness_skill_source_root", real_root)
    team.be("bob")
    skill_install.install_harness_skills()  # Bob's serve boot installed his shipped skills before he joined
    team.join("bob", shared)
    realm = RealmStore().get(shared.id)
    shipped = (skill_install.harness_skill_source_root() / _UPDATED / "SKILL.md").read_text(encoding="utf-8")
    assert _team_copy(realm) != shipped.strip()  # the two versions really differ
    return team, realm, shipped


def test_a_built_in_skill_equal_to_the_shipped_copy_is_never_held_on_pull(joined):
    """Mutation: drop the shipped-copy arm in ``skill_sync.classify_inbox_package`` -> the pull holds
    ``_UPDATED`` (``new_both``) and the status lists it, red (team-older and team-newer)."""
    _team, realm, shipped = joined
    assert _held(realm.id) == []
    status = _status(realm.id)
    assert _skill_rows(status) == []
    assert _UPDATED not in (status.get("skills_drift") or [])
    # Neither held nor adopted: the local copy is still this install's shipped one.
    assert (get_shared_skills_dir() / _UPDATED / "SKILL.md").read_text(encoding="utf-8") == shipped


def test_a_members_own_edit_meeting_a_changed_team_copy_still_holds(joined):
    """Mutation: ``skill_install.is_shipped_harness_skill_copy`` answers True for every harness slug whatever its
    content -> Bob's edit is never held, red."""
    team, realm, _shipped = joined
    assert _held(realm.id) == []
    # Bob edits his copy; Alice then publishes another change to the team's.
    skill = get_shared_skills_dir() / _UPDATED / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nBob's own rule.\n", encoding="utf-8")
    team.be("alice")
    alice_skill = get_shared_skills_dir() / _UPDATED / "SKILL.md"
    alice_skill.write_text(alice_skill.read_text(encoding="utf-8") + "\nAlice's own rule.\n", encoding="utf-8")
    publish_realm_sync(realm.id)
    team.be("bob")
    assert _held(realm.id) == [_UPDATED]
