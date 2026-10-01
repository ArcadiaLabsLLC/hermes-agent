"""``harness persona list`` builds its rows without profile readiness (w3-perf).

The wire row (``persona_instance_summary``) keeps only the tool-visibility head
scalars — permission mode, mutation boundary, tool and blocked counts, effective
toolsets — and none of them depends on readiness. Readiness was nevertheless
computed per row and thrown away: per profile home a credential-pool load, an
OAuth-grant heal and a full plugin discovery, ~29 s of a 47 s live run.

Two pins:

* the reply is byte-identical to what it was before the cut, on a fixture home
  (``tests/fixtures/persona_list_wire.json``, generated from ``69305cc48a`` with
  this file's own builder; volatile timestamps normalised);
* the listing reaches no readiness and no credential pool, with a POSITIVE
  CONTROL: ``persona-instance detail`` — which does emit readiness — trips the
  same recorders on the same home, so a zero here is not an instrument that sees
  nothing.

Killing mutation (applied, red recorded, reverted — the commit message has the
output): ``include_readiness=False`` -> ``True`` in ``persona_instance_summary``
reds ``test_persona_list_computes_no_readiness`` and leaves the shape pin green,
which is the cut's whole claim: readiness never reached the reply.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pytest

from hermes_cli.harness import build_parser

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "persona_list_wire.json"
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?$")


def _parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    build_parser(root.add_subparsers(dest="command"))
    return root


def _run(capsys, argv: list[str]) -> str:
    args = _parser().parse_args(argv)
    assert args.func(args) == 0
    return capsys.readouterr().out


def _normalised(text: str, tmp_root: Path) -> str:
    """The reply with wall-clock values and the per-test temp root replaced; the rest verbatim."""

    def walk(value):
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str) and _TIMESTAMP.match(value):
            return "<timestamp>"
        if isinstance(value, str):
            return value.replace(str(tmp_root), "<tmp>").replace("\\", "/")
        return value

    return json.dumps(walk(json.loads(text)), indent=2, sort_keys=False) + "\n"


@pytest.fixture
def roster_home(tmp_path, monkeypatch):
    """Three personas across two profiles, one on the Codex provider (the branch
    whose readiness loads a credential pool)."""

    from agent_runtime.models import AgentPersona
    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.store import AgentStore

    home = tmp_path / "hermes-home"
    for profile in ("alpha", "beta"):
        (home / "profiles" / profile).mkdir(parents=True, exist_ok=True)
        (home / "profiles" / profile / "config.yaml").write_text("model: {}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    personas = [
        AgentPersona(id="widget", display_name="Widget Agent", role="dev", model=None, provider=None,
                     api_mode="codex_responses", toolsets=["file"], system_prompt_path="", hermes_profile="alpha"),
        AgentPersona(id="gadget", display_name="Gadget Agent", role="qa", model="gpt-5.4", provider="openai-codex",
                     api_mode="codex_responses", toolsets=["file", "web"], system_prompt_path="",
                     hermes_profile="beta"),
        AgentPersona(id="sprocket", display_name="Sprocket", role="dev", model=None, provider=None,
                     api_mode="codex_responses", toolsets=[], system_prompt_path="", hermes_profile="alpha",
                     skills=["plan"]),
    ]
    store = AgentStore()
    for persona in personas:
        PersonaInstanceStore().ensure_for_persona(store.save(persona))
    return home


def test_persona_list_reply_is_byte_identical_to_before_the_cut(roster_home, capsys, tmp_path):
    reply = _normalised(_run(capsys, ["harness", "persona", "list", "--json"]), tmp_path)
    assert reply == GOLDEN.read_text(encoding="utf-8")


def test_persona_list_computes_no_readiness(roster_home, capsys, monkeypatch):
    import agent.credential_pool as credential_pool
    import agent_runtime.tool_visibility as tool_visibility

    calls: list[str] = []
    real_readiness = tool_visibility.profile_readiness_for_persona
    real_load_pool = credential_pool.load_pool

    def readiness(persona, *a, **kw):
        calls.append(f"readiness:{persona.id}")
        return real_readiness(persona, *a, **kw)

    def load_pool(provider):
        calls.append(f"load_pool:{provider}")
        return real_load_pool(provider)

    monkeypatch.setattr(tool_visibility, "profile_readiness_for_persona", readiness)
    monkeypatch.setattr(credential_pool, "load_pool", load_pool)

    rows = json.loads(_run(capsys, ["harness", "persona", "list", "--json"]))["persona_instances"]
    assert len(rows) == 3 and all("tool_count" in row for row in rows)
    assert calls == []

    # Positive control: the detail verb emits readiness, so the same recorders see it.
    gadget = next(row["persona_instance_id"] for row in rows if row["persona_id"] == "gadget")
    _run(capsys, ["harness", "persona-instance", "detail", gadget, "--json"])
    assert "readiness:gadget" in calls and "load_pool:openai-codex" in calls, calls
