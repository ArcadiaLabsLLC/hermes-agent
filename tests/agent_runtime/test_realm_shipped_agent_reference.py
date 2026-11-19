"""A realm that uses a shipped agent sends members a pointer, never its own copy.

Row ``RT-REALM-SHARES-A-SHIPPED-AGENT-BY-REFERENCE`` (design § 3, owner
2026-11-19). The publisher's install holds the shipped Neko and Base as
references and a user's copy of Neko (``based_on``); the realm places all
three. Publish carries no SOUL, prompt or memory file for a shipped agent and
only the reference body for it; the copy travels whole. A member's pull leaves
their shipped agents byte-identical, even when an older publisher sends a full
definition and profile files for one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime import paths, yaml_io
from agent_runtime.bundled_agents import reference_record, shipped_agent
from agent_runtime.bundled_agents.realm import REFERENCE_BODY, WITHHELD_REASON
from agent_runtime.models import AgentPersona
from agent_runtime.persona_config_sync import PROJECTION_KIND, PROJECTION_RELATIVE_PATH, apply_persona_config_pull
from agent_runtime.profile_artifact_sync import apply_profile_artifact_pull
from agent_runtime.realm_sync.families import published_relative_path
from agent_runtime.store import AgentStore, RealmStore, WorkspaceStore
from hermes_cli.profiles import get_profile_dir
from hermes_constants import get_config_path

NEKO = "neko_supervisor"
COPY = "neko_beta"
SHIPPED = ("base", NEKO)


def _profile(name: str, soul: str) -> Path:
    home = get_profile_dir(name)
    (home / "memories").mkdir(parents=True, exist_ok=True)
    (home / "SOUL.md").write_text(soul, encoding="utf-8")
    (home / "config.yaml").write_text("{}\n", encoding="utf-8")
    (home / "memories" / "MEMORY.md").write_text(f"{name} remembers this install.", encoding="utf-8")
    return home


def _member_config() -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_io.dump({"agent_runtime": {"personas": {}}}, sort_keys=True), encoding="utf-8")


def _install_with_shipped_agents() -> None:
    _member_config()
    _profile("neko", shipped_agent(NEKO).soul_text())
    _profile("base", "")
    store = AgentStore()
    for persona_id in SHIPPED:
        store.save(reference_record(shipped_agent(persona_id)))


def _realm(tmp_path: Path, agent_ids: list[str]) -> str:
    realm = RealmStore().create(name="Realm")
    ws = WorkspaceStore().create(name="WS", realm_id=realm.id)
    ws.agent_ids = list(agent_ids)
    WorkspaceStore().save(ws)
    realm = RealmStore().get(realm.id)
    realm.workspace_ids.append(ws.id)
    realm.sync_manifest_ref = str(tmp_path / "sync_repo")
    RealmStore().save(realm)
    WorkspaceStore().set_active(ws.id)
    return realm.id


@pytest.fixture
def publisher(tmp_path):
    _install_with_shipped_agents()
    _profile("neko-beta", "You are Neko Beta, the owner's own tuned SOUL.")
    AgentStore().save(AgentPersona(
        COPY, "Neko Mission Lead Beta", "alice_supervisor", None, None, None,
        hermes_profile="neko-beta", skills=["harness-runtime-model", "systematic-debugging"],
        soul_overlay_path="SOUL.md", include_profile_memory=True,
        based_on={"id": NEKO, "name": "Neko Mission Lead"},
    ))
    return _realm(tmp_path, [NEKO, "base", COPY])


def test_publish_sends_reference_only(publisher):
    from agent_runtime.realm_sync import _resolve_artifacts_with_projection

    resolved = _resolve_artifacts_with_projection(publisher)

    published = {artifact.relative_path.replace("\\", "/") for artifact in resolved.artifacts}
    for profile in ("neko", "base"):
        assert not [path for path in published if path.startswith(f"store/profile_files/{profile}/")]
    assert not [a for a in resolved.artifacts if a.persona_id in SHIPPED]
    withheld = {row["persona_id"]: row["reason"] for row in resolved.profile_files_withheld}
    assert withheld[NEKO] == withheld["base"] == WITHHELD_REASON
    personas = resolved.projection.personas
    assert personas[NEKO] == REFERENCE_BODY and personas["base"] == REFERENCE_BODY
    assert resolved.projection.shipped == {pid: shipped_agent(pid).version for pid in SHIPPED}
    document = yaml_io.load(resolved.projection.to_bytes().decode("utf-8"))
    assert document["shipped_agents"][NEKO] == shipped_agent(NEKO).version
    # The copy travels whole: its definition with "based on", its SOUL and memory.
    assert personas[COPY]["based_on"] == {"id": NEKO, "name": "Neko Mission Lead"}
    assert personas[COPY]["display_name"] == "Neko Mission Lead Beta"
    assert personas[COPY]["skills"] == ["harness-runtime-model", "systematic-debugging"]
    assert published_relative_path("neko-beta", "SOUL.md") in published
    assert published_relative_path("neko-beta", "memories/MEMORY.md") in published


def _older_publisher_subtree(tmp_path: Path) -> Path:
    """What an owner on an older build publishes: full bodies and files for Base and Neko."""

    subtree = tmp_path / "pulled"
    target = subtree.joinpath(*PROJECTION_RELATIVE_PATH.split("/"))
    target.parent.mkdir(parents=True)
    old_neko = {**shipped_agent(NEKO).definition, "skills": ["their-own-skill"], "display_name": "Their Neko"}
    old_neko = {key: value for key, value in old_neko.items() if value not in (None, "", [])}
    target.write_text(yaml_io.dump({
        "kind": PROJECTION_KIND, "schema_version": 1,
        "personas": {NEKO: old_neko, "base": dict(REFERENCE_BODY)},
    }, sort_keys=True), encoding="utf-8")
    for dest, text in (("SOUL.md", "An older owner's Neko SOUL."), ("memories/MEMORY.md", "The owner's memory.")):
        path = subtree.joinpath(*published_relative_path("neko", dest).split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return subtree


def _shipped_bytes() -> dict[str, bytes]:
    roots = [paths.store_root() / "agents", get_profile_dir("neko"), get_profile_dir("base")]
    files = {str(p): p.read_bytes() for root in roots for p in root.rglob("*") if p.is_file()}
    files[str(get_config_path())] = get_config_path().read_bytes()
    return files


def test_pull_leaves_shipped_agent_unchanged(tmp_path):
    _install_with_shipped_agents()
    subtree = _older_publisher_subtree(tmp_path)
    before = _shipped_bytes()

    personas = apply_persona_config_pull("realm", subtree)
    files = apply_profile_artifact_pull("realm", subtree)

    assert _shipped_bytes() == before
    assert personas.shipped == ["base", NEKO] and personas.shipped_ignored == [NEKO]
    assert personas.adopted == [] and personas.held == [] and personas.changed is False
    assert files.adopted == [] and files.changed is False
    assert sorted(files.shipped) == ["neko:SOUL.md", "neko:memories/MEMORY.md"]
    assert "neko" not in files.created_profiles
    # A second pull reads the same: nothing became a pending local change.
    again = apply_persona_config_pull("realm", subtree)
    assert again.kept_local == [] and again.held == [] and again.changed is False


def test_pull_places_a_shipped_agent_the_install_never_held(tmp_path):
    _member_config()
    subtree = _older_publisher_subtree(tmp_path)

    summary = apply_persona_config_pull("realm", subtree)

    assert summary.shipped_placed == ["base", NEKO] and summary.changed is True
    neko = AgentStore().get(NEKO)
    assert neko.origin == "eternia" and neko.display_name == "Neko Mission Lead"
    assert neko.skills == shipped_agent(NEKO).definition["skills"]


def test_a_pulled_copy_keeps_its_based_on(tmp_path):
    from agent_runtime.config import ensure_persisted_personas

    _install_with_shipped_agents()
    subtree = tmp_path / "pulled"
    target = subtree.joinpath(*PROJECTION_RELATIVE_PATH.split("/"))
    target.parent.mkdir(parents=True)
    body = {"display_name": "Neko Mission Lead Beta", "role": "alice_supervisor",
            "based_on": {"id": NEKO, "name": "Neko Mission Lead"}}
    target.write_text(yaml_io.dump({"kind": PROJECTION_KIND, "schema_version": 1, "personas": {COPY: body}}),
                      encoding="utf-8")

    summary = apply_persona_config_pull("realm", subtree)

    assert summary.adopted == [COPY]
    copy = next(p for p in ensure_persisted_personas() if p.id == COPY)
    assert copy.based_on == {"id": NEKO, "name": "Neko Mission Lead"}
