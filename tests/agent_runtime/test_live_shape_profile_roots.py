"""Live-shape profile roots load through the snapshot producer (design sweep D3.05).

A config-reading change used to be tested against one hand-written key on one
hand-written config, never against a root shaped like the operator's — and the
2026-10-09 refusal that took the live producer down was a key only the live
configs carried. ``tests/fixtures/profile_roots/live-2026-10/`` holds sanitized
copies of four of the operator's ten profiles, one per shape
(``scripts/sanitize_profile_config.py``; persona, toolset and model names only):

* ``base`` — the bundled minimum (5 personas, ~150 keys);
* ``neko`` — the full operator persona home (5 personas, ~700 keys);
* ``launcher-qa`` — the lane/QA home (1 persona, ~430 keys);
* ``gpt-launcher`` — the persona-less home (no ``agent_runtime`` section at all).

Each profile, made the active home over a root holding all four, runs the
producer's reads in order — ``load_agent_runtime_config``,
``persona_records_from_config``, ``merge_persisted_personas`` and each persona's
bound-profile declaration — and then ``build_snapshot`` over a store holding
those personas, so a raise is attributed to the read that raised. Every issue
code the root yields must be one ``expected_issues.json`` says it is KNOWN to
carry; the snapshot's agents are the config's enabled personas plus one
auto-discovered ``profile_<name>`` row per profile no persona binds.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_runtime.persona_lifecycle import DISABLED_ROLE_TOKENS

_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "profile_roots" / "live-2026-10"
_PROFILES = ("base", "neko", "launcher-qa", "gpt-launcher")


def _install_root(monkeypatch, active: str) -> Path:
    from agent_runtime.parse_cache import clear_parse_cache
    from hermes_cli.profiles import get_profile_dir

    homes = {}
    for profile in _PROFILES:
        home = get_profile_dir(profile)
        home.mkdir(parents=True, exist_ok=True)
        for name in ("config.yaml", "profile.yaml"):
            shutil.copyfile(_ROOT / profile / name, home / name)
        homes[profile] = home
    monkeypatch.setenv("HERMES_HOME", str(homes[active]))
    clear_parse_cache()
    return homes[active]


def test_the_fixture_root_holds_the_four_shapes():
    assert sorted(p.name for p in _ROOT.iterdir() if p.is_dir()) == sorted(_PROFILES)
    for profile in _PROFILES:
        assert (_ROOT / profile / "profile.yaml").read_text(encoding="utf-8") == "{}\n"
        assert isinstance(json.loads((_ROOT / profile / "expected_issues.json").read_text(encoding="utf-8")), list)


@pytest.mark.parametrize("profile", _PROFILES)
def test_a_live_shape_profile_root_loads_through_the_producer(profile, monkeypatch):
    from agent_runtime.config import load_agent_runtime_config, merge_persisted_personas, persona_records_from_config
    from agent_runtime.config.persona_records import legacy_persona_toolsets_issues
    from agent_runtime.persona_profiles import declared_lane_toolsets
    from agent_runtime.snapshot import build_snapshot
    from agent_runtime.store import AgentStore

    _install_root(monkeypatch, profile)
    expected = set(json.loads((_ROOT / profile / "expected_issues.json").read_text(encoding="utf-8")))

    cfg = load_agent_runtime_config()
    records = persona_records_from_config(cfg)
    merged = merge_persisted_personas([], cfg)
    assert sorted(p.id for p in merged) == sorted(p.id for p in records) == sorted(cfg.personas)

    codes = {issue.kind.value for issue in legacy_persona_toolsets_issues(cfg.personas)}
    for persona in records:
        codes |= {issue.kind.value for issue in declared_lane_toolsets(persona).issues}
    assert codes <= expected, f"{profile}: issue codes {sorted(codes - expected)} are not known to this root"

    store = AgentStore()
    for persona in records:
        store.save(persona)
    snapshot = build_snapshot(build_info={"caller": "test", "reason": "live-shape"})
    # The producer's roster: every config persona not disabled, plus one
    # auto-discovered ``profile_<name>`` row per live profile no persona binds.
    owned = {p.hermes_profile for p in records if p.hermes_profile}
    roster = {p.id for p in records if p.role not in DISABLED_ROLE_TOKENS}
    roster |= {f"profile_{name}" for name in _PROFILES if name not in owned}
    assert sorted(row["persona_id"] for row in snapshot["agents"]) == sorted(roster)
