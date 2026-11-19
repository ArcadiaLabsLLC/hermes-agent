"""``hermes harness init`` gives a fresh root Neko Mission Lead, and nothing else ever.

Row ``RT-FRESH-INSTALL-SEEDS-NEKO`` (owner 2026-11-18): a new install's default
agent is Neko; a root holding any persona gains nothing; a second init is a
no-op; the shipped SOUL says nothing about the owner. ``base`` is untouched.
"""

from __future__ import annotations

import argparse
import json

from agent_runtime import fresh_install_seed
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.models import AgentPersona
from agent_runtime.store import AgentStore
from hermes_cli.harness import build_parser
from hermes_cli.profiles import get_profile_dir


def _init(capsys) -> dict:
    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["harness", "init", "--json"])
    capsys.readouterr()
    assert args.func(args) == 0
    return json.loads(capsys.readouterr().out)


def _tree(root):
    return sorted(
        (str(p.relative_to(root)), p.read_bytes() if p.is_file() else b"")
        for p in root.rglob("*")
    )


def test_a_fresh_root_gets_neko_mission_lead_with_her_profile_and_soul(capsys):
    data = _init(capsys)

    assert data["personas"] == ["neko_supervisor"]
    neko = AgentStore().get("neko_supervisor")
    assert neko.display_name == "Neko Mission Lead"
    assert neko.hermes_profile == "neko"
    assert (neko.model, neko.provider, neko.api_mode) == (None, None, None)
    assert neko.skills == ["harness-runtime-model"]
    assert neko.role == "alice_supervisor"
    home = get_profile_dir("neko")
    shipped = fresh_install_seed._SOUL_SOURCE.read_text(encoding="utf-8")
    assert (home / "SOUL.md").read_text(encoding="utf-8") == shipped
    assert (home / "config.yaml").is_file()


def test_a_second_init_changes_nothing(capsys):
    first = _init(capsys)
    home = get_profile_dir("neko")
    record = AgentStore().get("neko_supervisor")
    before = _tree(home)

    assert _init(capsys) == first
    assert _tree(home) == before
    assert AgentStore().get("neko_supervisor") == record
    # Not merely the same bytes: the seed declines outright once a persona exists.
    assert fresh_install_seed.seed_fresh_install_persona(load_agent_runtime_config()) is None


def test_a_root_holding_any_persona_gains_no_neko(capsys):
    AgentStore().save(AgentPersona("someone", "Someone", "agent", None, None, None))

    data = _init(capsys)

    assert data["personas"] == ["someone"]
    assert not get_profile_dir("neko").exists()


def test_a_neko_profile_the_seed_did_not_stage_is_never_overwritten(capsys):
    home = get_profile_dir("neko")
    home.mkdir(parents=True)
    (home / "SOUL.md").write_text("the user's own neko", encoding="utf-8")

    data = _init(capsys)

    assert data["personas"] == []
    assert (home / "SOUL.md").read_text(encoding="utf-8") == "the user's own neko"


def test_the_shipped_soul_says_nothing_about_the_owner():
    soul = fresh_install_seed._SOUL_SOURCE.read_text(encoding="utf-8")

    assert soul.strip()
    assert "tony" not in soul.lower()
