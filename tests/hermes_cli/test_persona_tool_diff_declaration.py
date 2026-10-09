"""``persona tool-diff`` reports WHERE the capability came from (S0a A2).

Plan: ``docs/agent-runtime-harness/archive/s0a-atlas-cleanup.md`` §2 A2.

The defect this closes is an accounting one. Three copies of a per-persona
``toolsets`` list exist (profile config, store row, realm-sync body) and since
S0a A1 none of them admits anything — the harness lane reads the bound profile's
own ``toolsets:`` key. A preview that printed the persona list (and nothing about
the declaration) let an operator read a capability set no turn had ever run with,
with no way to tell a declaration from a default.

Every case drives the REAL argparse tree through ``args.func``, because the wire
row and the text line are both operator-facing surfaces and a handler poked
directly would not prove the verb still spells its positional argument.
"""

from __future__ import annotations

import argparse
import json

import pytest


@pytest.fixture(autouse=True)
def hermetic_runtime_root(tmp_path, monkeypatch):
    from agent_runtime import paths

    root = tmp_path / "agent-runtime"
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root))
    resolved = paths.store_root().resolve()
    assert resolved == root.resolve() or root.resolve() in resolved.parents
    return root


@pytest.fixture
def bound_profile_home():
    """Provision the profile home the seeded persona is bound to.

    Local rather than imported: ``tests/agent_runtime/conftest.py``'s
    ``bundled_persona_profiles`` does not reach this package, and the
    declaration reader resolves the PERSONA's bound profile — an absent home
    would resolve ``profile_unresolved`` and this file would be asserting the
    fallback instead of the read.
    """

    from hermes_cli.profiles import get_profile_dir

    home = get_profile_dir("gpt-launcher")
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("agent:\n  model: gpt-5.5\n", encoding="utf-8")
    from agent_runtime.parse_cache import clear_parse_cache

    clear_parse_cache()
    return home


def _seed_persona(persona_id: str = "dev"):
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore

    persona = AgentPersona(
        id=persona_id,
        display_name="Launcher Dev Agent",
        role="dev",
        model=None,
        provider=None,
        api_mode="codex_responses",
        system_prompt_path="",
        hermes_profile="gpt-launcher",
    )
    AgentStore().save(persona)
    return persona


def _dispatch(argv: list[str]) -> int:
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(argv)
    return args.func(args)


def _tool_diff(persona_id: str, *flags: str) -> int:
    return _dispatch(["harness", "persona", "tool-diff", persona_id, *flags])


def test_the_json_row_carries_the_declaration_and_no_legacy_list(
    bound_profile_home, capsys
):
    _seed_persona()

    assert _tool_diff("dev", "--json") == 0
    payload = json.loads(capsys.readouterr().out)["tool_visibility"]

    declaration = payload["toolset_declaration"]
    assert declaration["declared"] == ["harness_core"]
    assert declaration["source"] in {"lane_default", "profile_config"}
    # The persona-level list was deleted 2026-10-08 (tool-visibility split,
    # slice 1): the wire row carries the declaration and nothing beside it.
    assert "persona_list" not in declaration
    assert "persona_toolsets" not in payload
    assert "persona_toolsets_in_force" not in payload
    assert payload["effective_toolsets"] == declaration["toolsets"]


def test_the_text_mode_names_the_source(
    bound_profile_home, capsys
):
    """The operator's actual read. Without these two lines the only observable
    difference between "the profile declares harness_core" and "this profile
    declares nothing and the lane defaulted" is invisible."""

    _seed_persona()

    assert _tool_diff("dev") == 0
    out = capsys.readouterr().out

    # 43 -> 44: S2b registered ``agent_chat_installs`` into the ``agent_chat``
    # toolset, which ``harness_core`` includes by NAME. Re-measured with the S0a
    # ratchet in the same wave (``test_harness_core_ratchet.py``), never adjusted
    # to make a red go green. 44 -> 45: HQ1 (``8767fbf7a1``) added ``harness_query``
    # to ``agent_chat``; the same ratchet reads DECLARED_TOOL_COUNT = 45.
    assert "dev: 45 tools" in out
    assert "toolsets: harness_core (" in out
    assert "persona-level toolsets list ignored" not in out


def test_the_verb_still_requires_its_positional_persona_id():
    """The manual's View row used to say ``persona tool-diff --json`` with no id
    (S0a §0.4) — a documented command that exits 2. A4 fixes the row; this pins
    the fact the row has to respect."""

    with pytest.raises(SystemExit):
        _dispatch(["harness", "persona", "tool-diff", "--json"])


def test_an_unknown_declared_toolset_prints_as_a_requirement_failure(
    bound_profile_home, capsys
):
    """Slice 1 of the tool-visibility split (2026-10-08): the declaration's typed
    issues reach the operator through ``requirement_failures`` — the join between
    ``ToolsetDeclaration.issues`` and ``tool_visibility._requirement_failures``,
    pinned where the operator reads it."""

    (bound_profile_home / "config.yaml").write_text(
        "toolsets:\n  - harness_core\n  - eternia_lense\n", encoding="utf-8"
    )
    from agent_runtime.parse_cache import clear_parse_cache

    clear_parse_cache()
    _seed_persona()

    assert _tool_diff("dev") == 0
    out = capsys.readouterr().out

    assert "requirement failure: unknown_toolset" in out
    assert "'eternia_lense'" in out
