"""A Developer-Edition ``config.yaml`` in a shared namespace cannot reopen what the bundle closed
(row RT-NAMESPACE-SHARED-CONFIG-CLOSURE; launcher plan EDITION_SWITCH_NAMESPACE_STORE §6 R6).

Both editions read one namespace, so its profile ``config.yaml`` may be written by the Developer
Edition: ``agent.disabled_toolsets: []`` or ``security.allow_lazy_installs: true``. The bundled
edition must not trust the file for either:

* CLOSURE — a toolset the bundled profile disables whose tool modules are absent from the shipped plan
  cannot be loaded by any config. The proof is the packager's own plan over the real profile, and the
  toolset -> module map is read from the live tool registry. Measured 2026-10-20: four disabled
  toolsets ship their modules ("present but off") and are refused by the config file alone —
  :data:`CONFIG_ONLY`, a shrink-only ratchet held by row RT-NAMESPACE-SHARED-CONFIG-SHELL-FAMILY.
* FENCE — ``HERMES_DISABLE_LAZY_INSTALLS=1`` is set by BOTH the namespace resolver
  (``FENCE_DEFAULTS``) and the harness process defaults, and ``pm.install.lazy_installs_allowed``
  refuses under it whatever ``security.allow_lazy_installs`` says. Each half is proven alone.
"""

from __future__ import annotations

import functools
import inspect
from pathlib import Path

import pytest

from agent_runtime.bundle_profiles.manifest import load_profile
from agent_runtime.process_env_defaults import apply_harness_process_env_defaults
from hermes_cli import _namespace_bootstrap as ns

LAZY = "HERMES_DISABLE_LAZY_INSTALLS"


def _handler_module(handler) -> str:
    target = inspect.unwrap(handler)
    while isinstance(target, functools.partial):
        target = inspect.unwrap(target.func)
    return getattr(target, "__module__", "") or ""


@pytest.fixture(scope="module")
def shipped() -> set[str]:
    from scripts.bundle_profile_package import first_party_plan

    modules, _forced, _index = first_party_plan(load_profile("bundled-desktop"))
    return modules


#: Bundled-disabled toolsets whose tool modules SHIP ("present but off": switched off, yet forced into
#: the plan), so only ``agent.disabled_toolsets`` in the shared ``config.yaml`` refuses them. A ratchet
#: that may only shrink — row RT-NAMESPACE-SHARED-CONFIG-SHELL-FAMILY (owner decision pending).
CONFIG_ONLY = frozenset({"terminal", "code_execution", "browser", "browser-use"})


def _toolset_modules() -> dict[str, set[str]]:
    """Each bundled-disabled toolset -> the modules defining its tools' handlers (live registry)."""
    from tools.registry import discover_builtin_tools, registry
    from toolsets import resolve_toolset

    discover_builtin_tools()
    return {toolset: {_handler_module(entry.handler) for name in resolve_toolset(toolset)
                      if (entry := registry.get_entry(name)) is not None}
            for toolset in load_profile("bundled-desktop").disabled_toolsets}


@pytest.mark.timeout(300)  # the desktop walk (~65 s cold)
def test_a_config_cannot_load_a_toolset_the_closure_switched_off(shipped: set[str]):
    assert "hermes_cli.main" in shipped  # positive control: the walk reached the serve entry
    by_toolset = _toolset_modules()
    config_only = {toolset for toolset, mods in by_toolset.items() if mods & shipped}
    assert config_only == CONFIG_ONLY, (
        "bundled-disabled toolsets whose tool modules ship (a namespace config.yaml could enable them): "
        f"{ {t: sorted(by_toolset[t] & shipped) for t in config_only} } — a new one is a leak; a fixed one "
        "leaves CONFIG_ONLY")
    closed = {toolset for toolset, mods in by_toolset.items() if mods and not mods & shipped}
    assert len(closed) >= 5  # positive control: the registry walk mapped the closure-refused toolsets


@pytest.fixture
def lazy_config(tmp_path: Path, monkeypatch) -> Path:
    """A namespace profile home whose config.yaml (the Developer Edition's) turns lazy installs ON."""
    home = tmp_path / "ns" / "acct-0123456789abcdef" / "profiles" / "base"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("security:\n  allow_lazy_installs: true\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv(LAZY, raising=False)
    return home


def _allowed() -> bool:
    from pm.install import lazy_installs_allowed

    return lazy_installs_allowed()


def test_the_config_alone_would_allow_lazy_installs(lazy_config: Path):
    assert _allowed() is True  # positive control: the fence tests below are not vacuous


def test_the_harness_process_defaults_fence_lazy_installs(lazy_config: Path, monkeypatch):
    env: dict[str, str] = {}
    apply_harness_process_env_defaults(env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert _allowed() is False


def test_the_namespace_fence_refuses_lazy_installs(lazy_config: Path, monkeypatch):
    for key, value in ns.FENCE_DEFAULTS.items():
        monkeypatch.setenv(key, value)
    assert _allowed() is False
