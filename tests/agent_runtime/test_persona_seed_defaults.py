"""Hermes seeds the approved door-fit keys into a persona's bound profile — absent keys only.

Plan: ``docs/agent-runtime-harness/planned/persona-create-seed-values-2026-10-15.md`` (S1 + S2,
lines 1 and 2). The writer is ``agent_runtime.persona_seed_defaults``; it runs from the
persona-mint door (``promote_profile_to_persona``) and from the plugin's startup sweep.
"""

from __future__ import annotations

import json

from agent_runtime import yaml_io

_PROFILE_CONFIG = """# operator comment that must survive
model:
  default: gpt-5.5   # inline comment
mcp_servers:
  files.local:
    command: node
    args: [server.js]
  remote:
    url: https://example.invalid/mcp
  pinned:
    command: python
    env:
      HERMES_HOME: /operator/chosen
credential_pool_strategies:
  anthropic: round_robin
"""


def _profile(name: str, body: str = _PROFILE_CONFIG, pooled=("anthropic", "openrouter")):
    from hermes_cli.profiles import get_profile_dir

    home = get_profile_dir(name)
    (home / "config.yaml").write_text(body, encoding="utf-8")
    pool = {provider: [{"id": f"{provider}-1", "access_token": "x"}] for provider in pooled}
    (home / "auth.json").write_text(json.dumps({"version": 1, "credential_pool": pool}), encoding="utf-8")
    return home


def _persona(profile: str):
    from agent_runtime.models import AgentPersona

    return AgentPersona(
        id=f"p_{profile}".replace("-", "_"),
        display_name=profile,
        role="worker",
        model="m",
        provider="openrouter",
        api_mode="chat_completions",
        system_prompt_path="",
        hermes_profile=profile,
    )


def test_the_seed_fills_absent_keys_and_keeps_every_operator_value(bundled_persona_profiles):
    from agent_runtime.persona_seed_defaults import seed_persona_profile

    home = _profile("qa")

    report = seed_persona_profile(home)

    assert report["error"] is None
    assert report["seeded"] == [
        "mcp_servers.files\\.local.env.HERMES_HOME",
        "credential_pool_strategies.openrouter",
    ]
    text = (home / "config.yaml").read_text(encoding="utf-8")
    assert "# operator comment that must survive" in text and "# inline comment" in text
    loaded = yaml_io.load(text)
    servers = loaded["mcp_servers"]
    assert servers["files.local"]["env"] == {"HERMES_HOME": "${HERMES_HOME}"}
    assert "env" not in servers["remote"]  # no child process, nothing to seed
    assert servers["pinned"]["env"] == {"HERMES_HOME": "/operator/chosen"}  # the operator's, kept
    assert loaded["credential_pool_strategies"] == {"anthropic": "round_robin", "openrouter": "least_used"}

    settled = (home / "config.yaml").read_bytes()
    assert seed_persona_profile(home)["seeded"] == []  # idempotent
    assert (home / "config.yaml").read_bytes() == settled


def test_minting_a_persona_seeds_its_profile(bundled_persona_profiles):
    """S1 at the fork's persona-create door; the control is a profile no persona is bound to."""

    from agent_runtime.persona_profiles import promote_profile_to_persona

    class _Store:
        def list_all(self):
            return []

        def save(self, persona):
            return persona

    minted = _profile("qa")
    bystander = _profile("gpt-launcher")
    bystander_before = (bystander / "config.yaml").read_bytes()

    promote_profile_to_persona("qa", slot_role="worker", personas={"t": _persona("qa")}, agent_store=_Store())

    servers = yaml_io.load((minted / "config.yaml").read_text(encoding="utf-8"))["mcp_servers"]
    assert servers["files.local"]["env"] == {"HERMES_HOME": "${HERMES_HOME}"}
    assert (bystander / "config.yaml").read_bytes() == bystander_before


def test_the_startup_sweep_seeds_every_bound_profile_once(bundled_persona_profiles):
    """S2: the fill-if-absent pass over existing personas; two personas on one profile seed it once."""

    from agent_runtime.persona_seed_defaults import seed_all_persona_profiles

    home = _profile("qa", pooled=())
    personas = [_persona("qa"), _persona("qa"), _persona("no-such-profile")]

    report = seed_all_persona_profiles(personas)

    assert [row["path"] for row in report["profiles"]] == [str(home / "config.yaml")]
    assert report["profiles"][0]["seeded"] == ["mcp_servers.files\\.local.env.HERMES_HOME"]
    assert seed_all_persona_profiles(personas)["profiles"] == []
