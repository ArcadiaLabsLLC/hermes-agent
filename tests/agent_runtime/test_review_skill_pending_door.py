"""RT-REVIEW-STAGED-SKILL-DOOR — the owner's door onto staged skill writes across profiles.

A background review's shared-skill write is staged in the AGENT PROFILE's
``pending/skills/``; the only door was upstream's interactive ``/skills`` under that
profile's home. ``runtime.skills.pending.*`` and ``harness skills pending`` list every
profile's staged writes and approve (upstream's replay) or reject one.

Killing mutations (recorded in the landing commit): ``list_staged`` reading only the
default home -> the cross-profile listing reds; ``approve_staged`` discarding before the
replay's success check -> the failed-replay test reds (the record is gone).
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.profile_context import process_home_scope
from agent_runtime.review_skill_pending import (
    SkillPendingError,
    SkillPendingRefusal,
    approve_staged,
    list_staged,
    reject_staged,
)
from agent_runtime.serve_rpc import skills_pending as rpc

SKILL_MD = "---\nname: door-demo\ndescription: A staged demo skill.\n---\n\n# Door demo\n\nBody.\n"


@pytest.fixture
def namespace(tmp_path, monkeypatch):
    root = tmp_path / "root"
    neko = root / "profiles" / "neko"
    neko.mkdir(parents=True)
    (root / "config.yaml").write_text("{}\n", encoding="utf-8")
    (neko / "config.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "_default_hermes_root_memo", None, raising=False)
    return root, neko


def _stage(home, payload):
    from tools import write_approval as wa

    with process_home_scope(home):
        return wa.stage_write(wa.SKILLS, payload, summary="[shared] demo", origin="background_review")


def test_the_listing_reaches_a_write_staged_in_an_agent_profile(namespace):
    _root, neko = namespace
    record = _stage(neko, {"action": "create", "name": "door-demo", "content": SKILL_MD})

    listing = list_staged()
    assert "neko" in listing["profiles_scanned"]
    assert [(row["profile"], row["id"], row["origin"], row["skill"]) for row in listing["pending"]] == [
        ("neko", record["id"], "background_review", "door-demo")]
    assert list_staged(profile="default")["pending"] == []


def test_approve_replays_under_the_profile_home_and_drops_the_record(namespace):
    _root, neko = namespace
    record = _stage(neko, {"action": "create", "name": "door-demo", "content": SKILL_MD})

    answer = rpc._runtime_skills_pending_approve(1, {"profile": "neko", "id": record["id"]})
    assert answer["result"]["applied"] is True, answer
    assert list(neko.joinpath("skills").rglob("SKILL.md")), "the replay wrote under neko's home"
    assert list_staged()["pending"] == []


def test_a_failed_replay_keeps_the_record(namespace):
    """Positive control for the drop-on-success rule: the same door, a payload the
    replay refuses (a patch of a skill that does not exist) — the record stays."""

    _root, neko = namespace
    record = _stage(neko, {"action": "patch", "name": "no-such-skill", "old_string": "a", "new_string": "b"})

    with pytest.raises(SkillPendingError) as refused:
        approve_staged(profile="neko", pending_id=record["id"])
    assert refused.value.code is SkillPendingRefusal.APPLY_FAILED
    assert [row["id"] for row in list_staged()["pending"]] == [record["id"]]


def test_reject_drops_unapplied_and_unknowns_are_typed(namespace):
    _root, neko = namespace
    record = _stage(neko, {"action": "create", "name": "door-demo", "content": SKILL_MD})

    assert reject_staged(profile="neko", pending_id=record["id"])["rejected"] is True
    assert not neko.joinpath("skills").exists() or not list(neko.joinpath("skills").rglob("SKILL.md"))
    gone = rpc._runtime_skills_pending_reject(2, {"profile": "neko", "id": record["id"]})
    assert gone["error"]["data"]["reason"] == "not_found"
    nobody = rpc._runtime_skills_pending_list(3, {"profile": "ghost"})
    assert nobody["error"]["data"]["reason"] == "unknown_profile"
    bad = rpc._runtime_skills_pending_approve(4, {"profile": "neko", "id": "../x"})
    assert bad["error"]["data"]["reason"] == "invalid_id"


def test_the_argv_twin_prints_the_same_listing(namespace, capsys):
    import argparse

    from hermes_cli import harness

    _root, neko = namespace
    record = _stage(neko, {"action": "create", "name": "door-demo", "content": SKILL_MD})
    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(["harness", "skills", "pending", "list", "--json"])
    assert args.func(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and [row["id"] for row in payload["pending"]] == [record["id"]]
