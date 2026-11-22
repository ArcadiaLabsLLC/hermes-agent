"""A feature gate asks the installed profile, never module presence alone.

RT-FU-A-PHONE-RUNS-A-FEATURE-ONLY-WHEN-ITS-PROFILE-SWITCHES-IT-ON: the phone ships switched-off modules kept
code imports unguarded (pinned: ``agent_runtime.work``, ``agent_runtime.git_cmd``, the batch dispatcher,
``agent_runtime.messaging``, ``agent_runtime.local_llama_adapter``, ``tools.process_registry``,
``hermes_cli.local_runtime``), so ``module_presence.shipped`` answers True there and every gate that asked
it started a feature the phone's profile switches off. ``module_presence.runs_here`` asks the profile
(``installed_profile``, ``models``) first.

* The source gate refuses a presence probe (``shipped`` / ``find_spec``) naming a module either bundle profile
  switches off. It over-approximates (an import guard trips it too) and proves a negative: no such probe is
  left outside :data:`IMPORT_GUARDS`, each with its reason.
* Each moved gate is read under the phone's installed profile (this host's platform made a phone one).

Killing mutations (applied, red recorded, reverted — see the commit message):
* ``runs_here`` without its profile check -> ``test_runs_here_asks_the_profile_before_presence`` and every
  phone case below red;
* any moved gate back to ``shipped("<module>")`` -> ``test_no_feature_gate_probes_a_switched_off_module`` red,
  naming the site.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import installed_profile, module_presence

ROOT = Path(__file__).resolve().parents[2]
#: The trees a runtime feature gate can live in (fork-owned and upstream-owned alike: an upstream file's
#: fork seam line is a gate too, ``hermes_cli/inventory.py``).
SCANNED = ("agent", "agent_runtime", "gateway", "hermes_cli", "plugins", "tools", "tui_gateway", "acp_adapter")
PROBES = frozenset({"shipped", "find_spec"})
#: ``path|module`` -> why that presence probe is an import guard, not a feature gate. Shrink-only.
IMPORT_GUARDS: dict[str, str] = {}


@pytest.fixture
def phone(monkeypatch):
    """This install made the phone's: CPython's mobile platforms are what select the phone profile."""
    monkeypatch.setattr(installed_profile, "PHONE_PLATFORMS",
                        frozenset({*installed_profile.PHONE_PLATFORMS, sys.platform}))
    assert installed_profile.installed_profile_name() == installed_profile.PHONE_PROFILE


def _switched_off() -> tuple[str, ...]:
    return tuple(sorted({*installed_profile.switched_off_modules(installed_profile.PHONE_PROFILE),
                         *installed_profile.switched_off_modules(installed_profile.DESKTOP_PROFILE)}))


def _is_off(module: str, off: tuple[str, ...]) -> bool:
    return any(module == o or module.startswith(o + ".") for o in off)


def _probe_sites(rel: str, source: str, off: tuple[str, ...]) -> set[str]:
    tree = ast.parse(source)
    constants = {target.id: node.value.value for node in tree.body if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                 for target in node.targets if isinstance(target, ast.Name)}
    sites = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name not in PROBES:
            continue
        arg = node.args[0]
        module = (arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                  else constants.get(arg.id) if isinstance(arg, ast.Name) else None)
        if module and _is_off(module, off):
            sites.add(f"{rel}|{module}")
    return sites


def _scan() -> set[str]:
    off = _switched_off()
    sites: set[str] = set()
    for top in SCANNED:
        for path in (ROOT / top).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            if "shipped(" not in source and "find_spec(" not in source:
                continue
            sites |= _probe_sites(path.relative_to(ROOT).as_posix(), source, off)
    return sites


def test_the_source_gate_sees_a_presence_probe_of_a_switched_off_module():
    """Positive control: a literal, a module constant and ``importlib.util.find_spec`` are each seen; a probe
    of a module no profile switches off is not."""
    source = ('import importlib.util\nDOOR = "agent_runtime.git_cmd"\n'
              'if shipped("agent_runtime.work.store"): pass\nif shipped(DOOR): pass\n'
              'importlib.util.find_spec("agent_runtime.messaging")\nshipped("agent_runtime.workspace_chat_fold")\n')
    assert _probe_sites("x.py", source, _switched_off()) == {
        "x.py|agent_runtime.work.store", "x.py|agent_runtime.git_cmd", "x.py|agent_runtime.messaging"}


def test_no_feature_gate_probes_a_switched_off_module():
    found = _scan()
    new = sorted(found - set(IMPORT_GUARDS))
    assert not new, ("a feature gate asks module presence of a module a bundle profile switches off; ask "
                     "agent_runtime.module_presence.runs_here (or list an import guard here, with why):\n"
                     + "\n".join(new))
    stale = sorted(set(IMPORT_GUARDS) - found)
    assert not stale, f"these import guards are gone; drop their rows: {stale}"


def test_the_models_reader_and_the_manifest_read_one_switched_off_list():
    from agent_runtime.bundle_profiles.manifest import load_profile

    for name in (installed_profile.PHONE_PROFILE, installed_profile.DESKTOP_PROFILE):
        assert installed_profile.switched_off_modules(name) == load_profile(name, validate=False).switched_off_modules


def test_a_module_is_switched_off_only_by_the_installed_bundle_profile(monkeypatch):
    """Moved from ``test_bundled_toolsets`` with the reader (RT-PHONE-A-PHONE-CALL-REACHES-ONLY-MODULES-ITS-
    BUNDLE-SHIPS (c)). Killing mutation: drop ``install_is_bundled``'s check -> the first assertion reds."""
    from agent_runtime import bundled_toolsets

    monkeypatch.setattr(installed_profile, "edition_bundled", lambda: False)
    monkeypatch.setattr(installed_profile, "PHONE_PLATFORMS", frozenset({"android", "ios"}))
    monkeypatch.setattr(installed_profile, "switched_off_modules", lambda _name: ("agent_runtime.work",))
    assert installed_profile.installed_switched_off("agent_runtime.work") is False  # a developer install
    monkeypatch.setattr(installed_profile, "edition_bundled", lambda: True)
    assert installed_profile.installed_switched_off("agent_runtime.work") is True
    assert installed_profile.installed_switched_off("agent_runtime.work.store") is True
    assert installed_profile.installed_switched_off("agent_runtime.work_store") is False  # a sibling name
    assert bundled_toolsets.installed_switched_off("agent_runtime.work") is True  # the stores door delegates


def test_runs_here_asks_the_profile_before_presence(phone):
    assert module_presence.shipped("agent_runtime.work")  # it ships (here, and pinned on the phone)
    assert not module_presence.runs_here("agent_runtime.work")
    assert module_presence.runs_here("agent_runtime.workspace_chat_fold")  # not switched off: presence decides
    assert not module_presence.batch_dispatcher_runs_here()


def test_runs_here_on_a_developer_install_is_presence():
    assert module_presence.runs_here("agent_runtime.work")
    assert module_presence.batch_dispatcher_runs_here()
    assert not module_presence.runs_here("agent_runtime.no_such_module")


def _serve_start(monkeypatch) -> list[str]:
    from agent_runtime.work_store import engine, persona_turn
    from hermes_cli.harness_parts.serve import queued_turns

    started: list[str] = []
    monkeypatch.setattr(persona_turn, "PersonaTurnExecutor", lambda **_: SimpleNamespace(wake_parked=lambda: None))
    monkeypatch.setattr(engine, "WorkEngine", lambda **hooks: SimpleNamespace(hooks=hooks))
    monkeypatch.setattr(engine, "start_work_engine", lambda **_: started.append("engine"))
    monkeypatch.setattr(queued_turns, "_batch_hooks", lambda session: started.append("batch") or {})
    for step in ("start_serve_scheduler", "start_brain_remote_ticker", "start_realmless_fold_ticker"):
        monkeypatch.setattr(queued_turns, step, lambda *a, _s=step, **k: started.append(_s))
    from agent_runtime.messaging import serve_lane

    monkeypatch.setattr(serve_lane, "start_messaging_bridge", lambda session: started.append("messaging"))
    queued_turns.start_serve_work_engine(SimpleNamespace(serve_request_home=None, drain_state=None,
                                                         liveness_stop=None))
    return started


def test_a_phone_serve_start_builds_only_what_its_profile_runs(monkeypatch, phone):
    """The executor and engine start (chat goals ride them; the Work tick lists no workspace there); the batch
    hooks, the brains' remote check and the messaging bridge do not."""
    assert _serve_start(monkeypatch) == ["engine", "start_serve_scheduler", "start_realmless_fold_ticker"]


def test_a_developer_serve_start_builds_every_step(monkeypatch):
    assert _serve_start(monkeypatch) == ["batch", "engine", "start_serve_scheduler", "start_brain_remote_ticker",
                                         "start_realmless_fold_ticker", "messaging"]


def test_a_phone_registers_no_verb_of_a_feature_its_profile_switches_off(monkeypatch, phone):
    from agent_runtime.serve_rpc import registry

    monkeypatch.setattr(registry, "_METHODS", {})
    for ensure in (registry._ensure_local_llama_methods, registry._ensure_work_methods,
                   registry._ensure_batch_methods, registry._ensure_messaging_methods):
        ensure()
    assert registry._METHODS == {}
    monkeypatch.setattr(installed_profile, "PHONE_PLATFORMS", frozenset({"android", "ios"}))  # positive control
    registry._ensure_work_methods()
    assert "runtime.work.capabilities" in registry._METHODS


def test_a_phone_asks_no_git_program(phone):
    from agent_runtime import host_tools
    from agent_runtime.work import service

    assert service.git_shipped() is False
    assert host_tools.git_runs() is False
    assert host_tools.git_resolution().source == "not_shipped"


def test_a_phone_has_no_local_engine(monkeypatch, phone):
    import contextlib

    from agent_runtime import managed_local_floor, operator_turn_runtime
    from agent_runtime.persona_chat_history import markers
    from agent_runtime.profile_runner import runner

    assert operator_turn_runtime._local_engine_shipped() is False
    assert managed_local_floor.managed_local_marker() is None
    assert markers._is_local_llama_provider("llamacpp") is False
    assert isinstance(runner._local_engine_turn_scope(SimpleNamespace()), contextlib.nullcontext)


def test_a_phone_lists_no_local_runtime_row_and_drains_no_background_process(monkeypatch, phone):
    from agent_runtime.dispatch_delivery import completions
    from hermes_cli import inventory

    assert inventory._local_runtime_row(SimpleNamespace(current_provider="llamacpp")) is None
    empty = completions.BackgroundDrain.empty_tally()
    # A drain would construct one: a namespace is not callable, so a drain on the phone raises.
    monkeypatch.setattr(completions, "BackgroundDrain", SimpleNamespace(empty_tally=lambda: dict(empty)))
    assert completions.drain_background_completions() == empty
