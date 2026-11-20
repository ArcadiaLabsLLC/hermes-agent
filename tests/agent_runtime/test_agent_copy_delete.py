"""Deleting an agent copy you made takes one step, and it is gone from every agent list.

Row ``RT-AN-INDEPENDENT-COPY-CANNOT-BE-DELETED`` (seen 2026-11-20 by w1118a-phoneN:
after a retire, the copy's definition and profile stayed and Mission Control still
listed it). Review w1118a.47 D5: one door, ``runtime.agent.delete``, retires every
instance (chats kept), archives the definition, and archives the copy's own profile
only when no other agent uses it; it refuses a shipped agent, a persona that is not a
copy, and an agent a realm selection holds. Driven through the door the app calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.config.roster import ensure_persisted_personas
from agent_runtime.fresh_install_seed import seed_fresh_install_persona
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.models import AgentPersona
from agent_runtime.store import AgentStore, RealmStore
from hermes_cli.profiles import get_profile_dir
from tests.agent_runtime.test_serve_rpc_agent_create import (
    _instances,
    qa_persona,  # noqa: F401 — the fixture, re-exported for this file
)


@pytest.fixture
def shipped():
    """The shipped agents, seeded while the install is still fresh (before ``qa_persona``)."""

    seed_fresh_install_persona(load_agent_runtime_config())


def _rpc(method: str, rid: str = "del", **params) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})


def _delete(persona_id: str) -> dict:
    return _rpc("runtime.agent.delete", persona_id=persona_id)


def _copy(name: str = "QA Agent copy") -> dict:
    """Eternia's "Create independent copy" (``runtime.persona.instance.create``)."""

    reply = _rpc("runtime.persona.instance.create", rid=name, persona_id="qa", display_name=name,
                 independent_agent=True, client_message_id=f"key-{name}")
    instance = reply["result"]
    persona = AgentStore().get(instance["persona_id"])
    return {"persona": persona, "instance_id": instance["persona_instance_id"], "home": Path(get_profile_dir(persona.hermes_profile))}


def _listed(persona_id: str) -> dict:
    ensure_install_identity(paths.store_root())
    directory = _rpc("runtime.agent.directory")["result"]["agents"]
    return {
        "store": persona_id in {p.id for p in AgentStore().list_all()},
        "roster": persona_id in {p.id for p in ensure_persisted_personas()},
        "directory": any(row["persona_id"] == persona_id for row in directory),
        "instances": any(i.persona_id == persona_id for i in _instances().values()),
    }


def _disk() -> tuple:
    profiles = get_profile_dir("qa").parent
    return (
        sorted(p.name for p in paths.agents_dir().glob("*.json")),
        sorted(p.name for p in profiles.iterdir()) if profiles.is_dir() else [],
        sorted(_instances()),
    )


def test_a_delete_removes_the_copy_from_every_list(qa_persona):
    # MUTATIONS: skip the definition's ``os.replace`` -> red (store/roster still list it);
    # skip the profile's ``os.replace`` -> red (the home stays).
    copy = _copy()
    pid = copy["persona"].id
    assert _listed(pid) == {"store": True, "roster": True, "directory": True, "instances": True}

    reply = _delete(pid)["result"]

    assert _listed(pid) == {"store": False, "roster": False, "directory": False, "instances": False}
    assert not copy["home"].exists()
    assert Path(reply["profile_archive"]).is_dir() and Path(reply["definition_archive"]).is_file()
    assert reply["profile_kept"] is None and reply["chats_kept"] is True
    assert [r["persona_instance_id"] for r in reply["retired_instances"]] == [copy["instance_id"]]
    # Archived, never erased: the instance row sits in the retire archive.
    assert Path(reply["retired_instances"][0]["archive_path"]).is_file()


def test_a_retry_after_a_lost_answer_reads_the_receipt(qa_persona):
    pid = _copy()["persona"].id
    first = _delete(pid)["result"]

    again = _delete(pid)

    assert again["result"]["already_deleted"] is True
    assert again["result"]["definition_archive"] == first["definition_archive"]


def test_a_profile_another_agent_uses_stays(qa_persona):
    # MUTATION: make ``_profile_verdict`` return (None, []) after the marker check -> red:
    # the shared profile is archived out from under the other agent.
    copy = _copy()
    profile = copy["persona"].hermes_profile
    AgentStore().save(AgentPersona("helper", "Helper", "agent", None, None, None, hermes_profile=profile))

    reply = _delete(copy["persona"].id)["result"]

    assert copy["home"].is_dir()
    assert reply["profile_kept"] == "in_use" and reply["profile_used_by"] == ["helper"]
    assert reply["profile_archive"] is None
    assert not _listed(copy["persona"].id)["store"]


def test_a_shipped_agent_is_refused(shipped, qa_persona):
    # MUTATION: drop the ``shipped_agent`` guard in ``_plan`` -> red: the reason reads
    # ``not_a_copy`` (the next guard), never the shipped refusal the app explains.
    before = _disk()

    reply = _delete("neko_supervisor")

    assert reply["error"]["data"]["reason"] == "shipped_agent"
    assert _disk() == before


def test_a_duplicate_of_a_shipped_agent_is_a_copy_and_goes(shipped, qa_persona):
    # MUTATION: drop the owner marker ``agent_duplicate._stage_profile`` writes -> red:
    # the duplicate's profile is ``not_its_own`` and stays to be found again.
    dup = _rpc("runtime.agent.duplicate", persona_id="neko_supervisor", name="Neko Beta")["result"]
    home = Path(get_profile_dir(dup["profile"]))

    reply = _delete(dup["persona_id"])["result"]

    assert reply["profile_kept"] is None and not home.exists()
    assert not _listed(dup["persona_id"])["roster"]
    assert _listed("neko_supervisor")["roster"]


def test_an_agent_that_is_not_a_copy_is_refused(qa_persona):
    # MUTATION: drop ``not _is_copy(persona)`` from the guard -> red: "qa" is deleted.
    before = _disk()

    reply = _delete("qa")

    assert reply["error"]["data"]["reason"] == "not_a_copy"
    assert _disk() == before


def test_an_agent_a_realm_selection_holds_is_refused(qa_persona):
    # MUTATION: drop the ``held_by_realm`` guard -> red: the copy is deleted.
    copy = _copy()
    realm = RealmStore().create(name="Team")
    RealmStore().set_agent_selection(realm.id, mode="selected", selection=[copy["persona"].id])
    before = _disk()

    reply = _delete(copy["persona"].id)

    assert reply["error"]["data"] == {
        "reason": "held_by_realm", "persona_id": copy["persona"].id,
        "realm_id": realm.id, "held_by": "agent_selection",
    }
    assert _disk() == before


def test_a_dormant_selection_does_not_hold_it(qa_persona):
    # MUTATION: drop the ``agent_publish_mode == "selected"`` test -> red: refused.
    copy = _copy()
    realm = RealmStore().create(name="Team")
    RealmStore().set_agent_selection(realm.id, mode="selected", selection=[copy["persona"].id])
    # ``workspace`` mode keeps the list but publishes none of it.
    RealmStore().set_agent_selection(realm.id, mode="workspace", selection=[])
    assert RealmStore().get(realm.id).agent_selection == [copy["persona"].id]

    assert "result" in _delete(copy["persona"].id)


def test_an_unknown_agent_and_bad_params_are_refused_typed(qa_persona):
    assert _delete("nobody")["error"]["data"]["reason"] == "persona_not_found"
    assert _rpc("runtime.agent.delete")["error"]["data"]["reason"] == "invalid_params"
    assert _rpc("runtime.agent.delete", persona_id="qa", force=True)["error"]["data"]["reason"] == "invalid_params"
