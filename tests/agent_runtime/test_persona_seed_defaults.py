"""Hermes seeds the approved door-fit keys into a persona's bound profile — absent keys only.

Plan: ``docs/agent-runtime-harness/archive/persona-create-seed-values-2026-10-15.md`` (S1 + S2,
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


# ── line 5: skills.disabled over mission_chat compatibility (plan § Amendment 2026-10-21, S5) ──


def _skill(home, name: str, surfaces: str) -> None:
    skill_dir = home / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\nmetadata:\n  hermes:\n    surfaces: [{surfaces}]\n---\nbody\n",
        encoding="utf-8",
    )


def _disabled(home) -> list:
    loaded = yaml_io.load((home / "config.yaml").read_text(encoding="utf-8")) or {}
    return list((loaded.get("skills") or {}).get("disabled") or [])


def test_line5_hides_the_incompatible_skill_keeps_the_operator_entry_and_releases_on_compat(
    bundled_persona_profiles,
):
    """KILLING MUTATIONS: write ``current ∪ computed`` (never release) -> the release step
    reds; drop the sidecar (the writer owns the whole list, ``disabled = computed``) ->
    the operator's ``foo`` is dropped on the second sweep -> red."""

    from agent_runtime.persona_seed_defaults import SEED_RECEIPT_NAME, seed_persona_profile
    from utils import atomic_roundtrip_yaml_update

    home = _profile("qa", body="model:\n  default: m\n", pooled=())
    _skill(home, "cli-only", "cli")
    _skill(home, "chat-ok", "mission_chat")

    first = seed_persona_profile(home)

    assert first["error"] is None
    assert _disabled(home) == ["cli-only"]
    receipt = json.loads((home / SEED_RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt == {"schema_version": 1, "seeded": {"skills.disabled": ["cli-only"]}}

    atomic_roundtrip_yaml_update(home / "config.yaml", "skills.disabled", ["cli-only", "foo"])
    seed_persona_profile(home)
    assert sorted(_disabled(home)) == ["cli-only", "foo"]

    _skill(home, "cli-only", "mission_chat")  # now compatible
    seed_persona_profile(home)
    assert _disabled(home) == ["foo"]
    receipt = json.loads((home / SEED_RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt["seeded"] == {"skills.disabled": []}


def test_line5_never_claims_a_name_the_operator_already_listed(bundled_persona_profiles):
    from agent_runtime.persona_seed_defaults import seed_persona_profile

    home = _profile("qa", body="skills:\n  disabled: [cli-only]\n", pooled=())
    _skill(home, "cli-only", "cli")

    seed_persona_profile(home)
    _skill(home, "cli-only", "mission_chat")
    seed_persona_profile(home)

    assert _disabled(home) == ["cli-only"], "the operator's own entry was released as if seeded"


def test_line5_resolves_the_home_at_call_time_not_the_ambient_one(bundled_persona_profiles):
    from agent_runtime.persona_seed_defaults import incompatible_skills

    qa = _profile("qa", body="model:\n  default: m\n", pooled=())
    other = _profile("backend-dev", body="model:\n  default: m\n", pooled=())
    _skill(qa, "cli-only", "cli")

    assert "cli-only" in incompatible_skills(qa)
    assert "cli-only" not in incompatible_skills(other)


def test_a_freshly_seeded_profile_matches_the_canonical_mcp_template(bundled_persona_profiles):
    """RT-MCP-TEMPLATE-VS-SEED-HERMES-HOME: the seed's line 1 and the readiness
    template name one ``env.HERMES_HOME``, so seeding never manufactures drift."""

    from agent_runtime.mcp_server_templates import canonical_mcp_server_yaml, mcp_server_template_issues
    from agent_runtime.persona_seed_defaults import seed_persona_profile

    block = "\n".join(
        line for line in canonical_mcp_server_yaml("launcher_qa").splitlines() if "HERMES_HOME" not in line
    )
    home = _profile("qa", body="mcp_servers:\n" + block + "\n", pooled=())

    unseeded = yaml_io.load((home / "config.yaml").read_text(encoding="utf-8"))["mcp_servers"]
    before = mcp_server_template_issues(unseeded)
    assert len(before) == 1 and "env.HERMES_HOME: missing" in before[0].summary  # positive control

    assert seed_persona_profile(home)["seeded"] == ["mcp_servers.launcher_qa.env.HERMES_HOME"]

    seeded = yaml_io.load((home / "config.yaml").read_text(encoding="utf-8"))["mcp_servers"]
    assert mcp_server_template_issues(seeded) == []
