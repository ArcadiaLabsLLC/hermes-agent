"""A ROOT-only knob written in a PROFILE config is named on each agent's declaration.

RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING: the operator's
own 2026-10 live profile (``tests/fixtures/profile_roots/live-2026-10/launcher-qa``) held
``agent_runtime.personas.neko_supervisor.chat_lane_restore_toolsets`` in a profile config,
where no reader looks; only ``harness doctor`` said so. The keys are the one list
``config.ROOT_ONLY_CONFIG_KEYS``; each profile copy is one typed
``root_only_knob_in_profile_config`` row on the declaration ``tool-diff``, the HUD and
Eternia print, naming the root config to move it to. The root value still applies.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from agent_runtime.models import AgentPersona
from agent_runtime.personas import DeclarationIssueKind

_KIND = DeclarationIssueKind.ROOT_ONLY_KNOB_IN_PROFILE_CONFIG


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _root_and_profile(monkeypatch, *, root: str, profile: str):
    """A root config and the active profile home's config (``HERMES_HOME`` = the profile)."""

    from agent_runtime.parse_cache import clear_parse_cache
    from hermes_cli.profiles import get_profile_dir
    from hermes_constants import get_default_hermes_root

    home = get_profile_dir("launcher-qa")
    home.mkdir(parents=True, exist_ok=True)
    (home / "profile.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    root_path = _write(get_default_hermes_root() / "config.yaml", root)
    profile_path = _write(home / "config.yaml", profile)
    clear_parse_cache()
    return root_path, profile_path


def _neko() -> AgentPersona:
    return AgentPersona(
        id="neko_supervisor", display_name="Neko", role="supervisor",
        model=None, provider=None, api_mode=None, hermes_profile="launcher-qa",
    )


def _issues(persona: AgentPersona):
    from agent_runtime.persona_profiles import declared_lane_toolsets

    return [issue for issue in declared_lane_toolsets(persona).issues if issue.kind is _KIND]


_ROOT_CLEAN = """
agent_runtime:
  redaction_mode: observe
"""

_PROFILE_RESTORE = """
agent_runtime:
  personas:
    neko_supervisor:
      chat_lane_restore_toolsets: [vision]
"""


def test_a_chat_lane_setting_in_a_profile_config_is_one_issue_naming_the_root(monkeypatch):
    # Red when ``personas.*.chat_lane_restore_toolsets`` leaves ROOT_ONLY_CONFIG_KEYS.
    root_path, profile_path = _root_and_profile(monkeypatch, root=_ROOT_CLEAN, profile=_PROFILE_RESTORE)

    issues = _issues(_neko())

    assert len(issues) == 1
    row = issues[0].row(entry_point_lane="mission_chat")
    assert row["code"] == "root_only_knob_in_profile_config"
    assert row["subject"] == "agent_runtime.personas.neko_supervisor.chat_lane_restore_toolsets"
    assert row["config_path"] == str(profile_path)
    assert str(root_path) in row["fix_hint"]
    assert row["fix_hint"].startswith("Move ")


def test_a_mission_chat_knob_in_a_profile_config_is_one_issue(monkeypatch):
    # Red when the six ``mission_chat`` ``_root_knob`` keys leave ROOT_ONLY_CONFIG_KEYS.
    _root_and_profile(
        monkeypatch,
        root=_ROOT_CLEAN,
        profile="""
        agent_runtime:
          mission_chat:
            default_max_seconds: 1800
        """,
    )

    assert [issue.detail for issue in _issues(_neko())] == ["agent_runtime.mission_chat.default_max_seconds"]


def test_a_copy_the_root_also_sets_says_delete_it(monkeypatch):
    _root_and_profile(
        monkeypatch,
        root="""
        agent_runtime:
          mission_chat:
            dispatch_max_concurrent: 2
        """,
        profile="""
        agent_runtime:
          mission_chat:
            dispatch_max_concurrent: 9
        """,
    )

    (issue,) = _issues(_neko())
    assert issue.set_in_root is True
    assert issue.row()["fix_hint"].startswith("Delete ")


def test_the_root_knob_still_applies_over_the_profile_copy(monkeypatch):
    """The issue reports the copy; it never makes the copy read (the 2026-07-23 shadowing)."""

    from agent_runtime.config import chat_lane_restore_toolsets, mission_chat_default_max_seconds

    _root_and_profile(
        monkeypatch,
        root="""
        agent_runtime:
          mission_chat:
            default_max_seconds: 600
          personas:
            neko_supervisor:
              chat_lane_restore_toolsets: [browser]
        """,
        profile="""
        agent_runtime:
          mission_chat:
            default_max_seconds: 1800
          personas:
            neko_supervisor:
              chat_lane_restore_toolsets: [vision]
        """,
    )

    assert chat_lane_restore_toolsets("neko_supervisor") == ["browser"]
    assert mission_chat_default_max_seconds() == 600.0


def test_a_per_agent_root_only_key_is_only_its_own_agents_issue(monkeypatch):
    # Red with the persona filter in ``persona_records.root_only_knob_issues`` removed.
    _root_and_profile(
        monkeypatch,
        root=_ROOT_CLEAN,
        profile="""
        agent_runtime:
          personas:
            dev:
              chat_lane_defer_tools: [browser_vault]
        """,
    )

    assert _issues(_neko()) == []


def test_a_config_that_is_the_root_raises_no_issue(monkeypatch):
    """A single-profile install: the active home IS the root, where the key is read."""

    # Red with the ``config_path == root_path`` skip in ``scan_misplaced_root_only_keys`` removed.
    from agent_runtime.parse_cache import clear_parse_cache
    from hermes_constants import get_default_hermes_root

    root = get_default_hermes_root()
    monkeypatch.setenv("HERMES_HOME", str(root))
    _write(root / "config.yaml", _PROFILE_RESTORE)
    clear_parse_cache()

    assert _issues(_neko()) == []


def test_a_scan_fault_yields_no_rows_and_never_raises(monkeypatch):
    # Red with the try/except in ``persona_profiles._root_only_knob_issues`` removed.
    import agent_runtime.config.loader as loader

    _root_and_profile(monkeypatch, root=_ROOT_CLEAN, profile=_PROFILE_RESTORE)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("scan fault")

    monkeypatch.setattr(loader, "scan_misplaced_root_only_keys", _boom)

    assert _issues(_neko()) == []


def test_every_root_knob_name_is_on_the_root_only_list():
    """A new ``knobs._root_knob`` name joins the one list, or its profile copy is silent again."""

    # Red when any ``mission_chat`` entry leaves ROOT_ONLY_CONFIG_KEYS.
    import agent_runtime.config.knobs as knobs
    from agent_runtime.config import ROOT_ONLY_CONFIG_KEYS

    tree = ast.parse(Path(knobs.__file__).read_text(encoding="utf-8"))
    names = {
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "_root_knob"
        and isinstance(node.args[1], ast.Constant)
    }
    assert len(names) == 6, sorted(names)
    listed = {path[1] for path, _reader in ROOT_ONLY_CONFIG_KEYS if path[0] == "mission_chat" and len(path) == 2}
    assert names <= listed, sorted(names - listed)


@pytest.mark.parametrize("key", ["chat_lane_restore_toolsets", "chat_lane_defer_tools"])
def test_the_live_shape_launcher_qa_copy_is_named(monkeypatch, key):
    """The 2026-10 live profile's own copy is the shape this row was filed from."""

    _root_and_profile(
        monkeypatch,
        root=_ROOT_CLEAN,
        profile=f"""
        agent_runtime:
          personas:
            alice_supervisor:
              {key}: [file]
        """,
    )

    # Filed under the legacy alias, it is still Neko's.
    assert [issue.detail for issue in _issues(_neko())] == [f"agent_runtime.personas.alice_supervisor.{key}"]
