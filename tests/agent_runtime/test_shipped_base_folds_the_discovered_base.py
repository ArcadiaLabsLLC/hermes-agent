"""An install that ran before the shipped agents were placed lists one Base, with its old chats on it.

Row ``RT-SHIPPED-BASE-LEAVES-A-SECOND-BASE-IN-AN-OLDER-NAMESPACE`` (review w1118a.44
D4). Seen live 2026-11-19 (w1118a-mccopy): a namespace whose first directory read came
before the shipped Base was placed held ``profile_base`` (profile discovery's agent over
the ``base`` profile); placing the shipped ``base`` listed Base twice in
``runtime.agent.directory``. The fixture is that namespace: discovery runs for real over
a ``base`` profile, then a realm pull seats the shipped Base (no sort run), or the store
already holds both and ``persona sort-shipped`` runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import instance_catalog, paths, profile_home, yaml_io
from agent_runtime.bundled_agents import reference_record, shipped_agent
from agent_runtime.bundled_agents.realm import REFERENCE_BODY
from agent_runtime.config import ensure_persisted_personas
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_config_sync import PROJECTION_KIND, PROJECTION_RELATIVE_PATH, apply_persona_config_pull
from agent_runtime.persona_instance_identity import load_persona_instance_aliases
from agent_runtime.profile_persona_discovery import reconcile_profile_personas
from agent_runtime.store import AgentStore
from hermes_cli import profiles as profile_mod
from hermes_cli.profiles import get_profile_dir
from hermes_constants import get_config_path
import hermes_constants

DISCOVERED = "profile_base"
OLD_CHANNEL = "personainst_profile_base"
SEAT_CHAT = "persona_chat_seat_on_the_old_base_0123456789ab"


@pytest.fixture
def older_namespace(monkeypatch):
    """A ``base`` profile, discovered as ``profile_base`` with its own channel and one workspace seat."""

    home = get_profile_dir("base")
    (home / "memories").mkdir(parents=True)
    (home / "SOUL.md").write_text("", encoding="utf-8")
    (home / "config.yaml").write_text("{}\n", encoding="utf-8")
    config = get_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(yaml_io.dump({"agent_runtime": {"personas": {}}}, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(hermes_constants, "named_profile_has_servable_identity", lambda path: True)
    monkeypatch.setattr(profile_mod, "list_profile_names", lambda: ["default", "base"])
    monkeypatch.setattr(
        profile_home, "available_profile_template_summaries", lambda: [SimpleNamespace(name="base", path="base")],
    )
    monkeypatch.setattr(instance_catalog, "read_install_identity", lambda root: SimpleNamespace(install_id="install"))
    assert [persona.id for persona in reconcile_profile_personas()] == [DISCOVERED]
    instances = PersonaInstanceStore()
    channel = instances.ensure_for_persona(AgentStore().get(DISCOVERED))
    seat = instances.add_instance(
        persona_id=DISCOVERED, placement_id="profile_base_ws_default_agent_1", workspace_id="ws_default",
        session_id=SEAT_CHAT,
    )
    return {"channel": channel, "seat": seat}


def _pull_seating_base(tmp_path: Path):
    subtree = tmp_path / "pulled"
    target = subtree.joinpath(*PROJECTION_RELATIVE_PATH.split("/"))
    target.parent.mkdir(parents=True)
    target.write_text(yaml_io.dump({
        "kind": PROJECTION_KIND, "schema_version": 1, "personas": {"base": dict(REFERENCE_BODY)},
    }, sort_keys=True), encoding="utf-8")
    return apply_persona_config_pull("realm", subtree)


def _sort(capsys, *flags: str) -> dict:
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(["harness", "persona", "sort-shipped", *flags, "--json"])
    capsys.readouterr()
    assert args.func(args) == 0
    return {entry["persona_id"]: entry for entry in json.loads(capsys.readouterr().out)["plan"]}


def _one_base(seat) -> None:
    """The directory Eternia reads lists one Base, and the old Base's chats are on it."""

    directory = instance_catalog.prepare_instance_catalog()["agents"]
    on_base = [row for row in directory if row["profile"] == "base"]
    assert {row["persona_id"] for row in on_base} == {"base"}
    assert [row["instance_id"] for row in on_base if row["canonical"]] == ["personainst_base"]
    assert [p.id for p in ensure_persisted_personas() if p.hermes_profile == "base"] == ["base"]
    instances = PersonaInstanceStore()
    moved = instances.get(seat.id)
    assert (moved.persona_id, moved.session_id) == ("base", SEAT_CHAT)
    # The old channel's chats open on the shipped Base's channel.
    assert load_persona_instance_aliases()[OLD_CHANNEL] == "personainst_base"
    assert instances.get(OLD_CHANNEL).id == "personainst_base"
    # Nothing deleted: the old channel and the old record are archived.
    assert list(paths.persona_instances_archive_dir().rglob(f"{OLD_CHANNEL}.json"))
    assert list((paths.store_root() / "agents_archive").rglob(f"{DISCOVERED}.json"))
    # Discovery does not make it again: the shipped Base owns the profile.
    assert reconcile_profile_personas() == []


def test_a_realm_pull_seating_base_folds_the_discovered_base(older_namespace, tmp_path):
    summary = _pull_seating_base(tmp_path)

    assert summary.shipped_placed == ["base"]
    assert AgentStore().get("base").origin == "eternia"
    _one_base(older_namespace["seat"])


def test_sort_shipped_plans_a_fold_when_the_store_holds_both(older_namespace, capsys):
    AgentStore().save(reference_record(shipped_agent("base")))

    plan = _sort(capsys, "--dry-run")
    assert (plan["base"]["action"], plan["base"]["fold"]) == ("fold", DISCOVERED)
    assert AgentStore().get(DISCOVERED).id == DISCOVERED

    receipt = _sort(capsys)
    assert receipt["base"]["folded"]["channels_folded"] == {OLD_CHANNEL: "personainst_base"}
    assert receipt["base"]["folded"]["instances_moved"] == [older_namespace["seat"].id]
    _one_base(older_namespace["seat"])


def test_a_discovered_base_the_person_renamed_stays_theirs(older_namespace, tmp_path):
    edited = AgentStore().get(DISCOVERED)
    edited.display_name = "My Helper"
    AgentStore().save(edited)

    _pull_seating_base(tmp_path)

    assert AgentStore().get(DISCOVERED).display_name == "My Helper"
    assert PersonaInstanceStore().get(OLD_CHANNEL).persona_id == DISCOVERED
    assert OLD_CHANNEL not in load_persona_instance_aliases()


def test_a_leftover_setting_under_the_folded_id_brings_no_profile_base_back(older_namespace, tmp_path):
    """RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT (review w1118a.45 D2): the
    fold archives ``profile_base``'s record, so a setting the person (or the QA model fixture)
    wrote under that id is all that is left of it — and it is a setting, not an agent."""

    from agent_runtime.config import chat_lane_restore_toolsets
    from agent_runtime.parse_cache import clear_parse_cache

    get_config_path().write_text(yaml_io.dump({"agent_runtime": {"personas": {
        DISCOVERED: {"chat_lane_restore_toolsets": ["file", "terminal"]},
    }}}, sort_keys=True), encoding="utf-8")
    clear_parse_cache()

    _pull_seating_base(tmp_path)

    _one_base(older_namespace["seat"])
    assert DISCOVERED not in {row["persona_id"] for row in instance_catalog.prepare_instance_catalog()["agents"]}
    assert DISCOVERED not in {p.id for p in ensure_persisted_personas()}
    assert chat_lane_restore_toolsets(DISCOVERED) == ["file", "terminal"]
