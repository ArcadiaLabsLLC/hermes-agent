"""``persona tool-diff`` names the plugin toolsets no profile declares (slice 2).

Plan: ``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md``
§3 slice 2. Acceptance: a fake plugin registering one tool into ``eternia_lens`` with the
persona on ``harness_core`` is named in the text line and in ``--json``; declaring it
clears both. Drives the REAL argparse tree through ``args.func``.
"""

from __future__ import annotations

import argparse
import json

import pytest

LENS = "eternia_lens"
LENS_TOOL = "eternia_lens_tool_diff_probe"


@pytest.fixture(autouse=True)
def hermetic_runtime_root(tmp_path, monkeypatch):
    from agent_runtime import paths

    root = tmp_path / "agent-runtime"
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root))
    resolved = paths.store_root().resolve()
    assert resolved == root.resolve() or root.resolve() in resolved.parents
    return root


@pytest.fixture
def profile_home():
    from agent_runtime.parse_cache import clear_parse_cache
    from hermes_cli.profiles import get_profile_dir

    home = get_profile_dir("gpt-launcher")
    home.mkdir(parents=True, exist_ok=True)

    def _declare(*names: str):
        body = "toolsets:\n" + "".join(f"  - {name}\n" for name in names)
        (home / "config.yaml").write_text(body, encoding="utf-8")
        clear_parse_cache()

    return _declare


@pytest.fixture
def lens_plugin():
    from hermes_cli.plugins import discover_plugins
    from tools.registry import registry

    discover_plugins()
    registry.register(
        name=LENS_TOOL,
        toolset=LENS,
        schema={"name": LENS_TOOL, "description": "probe", "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **kwargs: "{}",
    )
    try:
        yield
    finally:
        registry.deregister(LENS_TOOL)


def _seed_persona():
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore

    AgentStore().save(
        AgentPersona(
            id="dev",
            display_name="Launcher Dev Agent",
            role="dev",
            model=None,
            provider=None,
            api_mode="codex_responses",
            hermes_profile="gpt-launcher",
        )
    )


def _tool_diff(*flags: str) -> int:
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(["harness", "persona", "tool-diff", "dev", *flags])
    return args.func(args)


def test_tool_diff_names_an_undeclared_plugin_toolset(profile_home, lens_plugin, capsys):
    profile_home("harness_core")
    _seed_persona()

    assert _tool_diff() == 0
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l.startswith("registered but declared by no profile:")]
    assert len(lines) == 1, out
    assert LENS in lines[0].split(":", 1)[1].replace(" ", "").split(",")

    assert _tool_diff("--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert LENS in payload["undeclared_registered_toolsets"]


def test_declaring_the_toolset_clears_both(profile_home, lens_plugin, capsys):
    """Positive control: the same plugin, now declared, is named by neither reader."""

    profile_home("harness_core", LENS)
    _seed_persona()

    assert _tool_diff() == 0
    out = capsys.readouterr().out
    assert LENS not in "".join(l for l in out.splitlines() if l.startswith("registered but declared"))

    assert _tool_diff("--json") == 0
    assert LENS not in json.loads(capsys.readouterr().out)["undeclared_registered_toolsets"]
