"""A namespaced process never resolves a store/home outside its namespace (row RT-NAMESPACE-ROOT).

``agent_runtime.namespace.assert_namespace_isolation`` is the gate ``paths.store_root`` runs; the
``root_anchor`` refusal keeps a namespace's root out of the machine-wide config. Temp roots only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime import paths
from agent_runtime.namespace import NamespaceIsolationViolation, assert_namespace_isolation
from agent_runtime.resolution import RuntimeResolution, resolve_runtime
from agent_runtime.root_anchor import RootAnchorOutcome, publish_store_root_anchor


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    from hermes_cli import _namespace_bootstrap

    monkeypatch.setattr(_namespace_bootstrap, "long_paths_enabled", lambda: True)


@pytest.fixture
def layout(tmp_path: Path):
    base = tmp_path / ".hermes"
    folder = tmp_path / "hermes-namespaces"
    own = folder / "qa"
    env = {"HERMES_NAMESPACE": "qa", "HERMES_DEPENDENCY_ROOT": str(base), "LOCALAPPDATA": str(tmp_path / "appdata")}
    return env, base, folder, own


def _resolution(store: Path, home: Path) -> RuntimeResolution:
    return RuntimeResolution(store, "env", str(home), str(home / "config.yaml"), ())


def test_paths_inside_the_namespace_pass(layout):
    env, _, _, own = layout
    assert_namespace_isolation(_resolution(own / "agent-runtime", own / "profiles" / "base"), env=env)


@pytest.mark.parametrize(
    "where, store, home",
    [
        ("base", lambda b, f, o: b / "agent-runtime", lambda b, f, o: o / "profiles" / "base"),
        ("base", lambda b, f, o: o / "agent-runtime", lambda b, f, o: b),
        ("namespace:other", lambda b, f, o: f / "other" / "agent-runtime", lambda b, f, o: o / "profiles" / "base"),
        ("namespace:other", lambda b, f, o: o / "agent-runtime", lambda b, f, o: f / "other" / "profiles" / "base"),
        ("outside", lambda b, f, o: b.parent / "temp" / "agent-runtime", lambda b, f, o: o),
    ],
)
def test_a_path_in_the_base_another_namespace_or_elsewhere_raises(layout, where, store, home):
    env, base, folder, own = layout
    with pytest.raises(NamespaceIsolationViolation) as caught:
        assert_namespace_isolation(_resolution(store(base, folder, own), home(base, folder, own)), env=env)
    assert caught.value.reason == "namespace_isolation"
    assert f"lies in {where};" in caught.value.detail


def test_the_head_home_is_checked_too(layout):
    env, base, _, own = layout
    env = {**env, "HERMES_HEAD_HOME": str(base / "profiles" / "base")}
    with pytest.raises(NamespaceIsolationViolation):
        assert_namespace_isolation(_resolution(own / "agent-runtime", own / "profiles" / "base"), env=env)


def test_unset_or_base_is_a_no_op_even_over_the_base_root(layout):
    env, base, _, _ = layout
    live = _resolution(base / "agent-runtime", base)
    for value in (None, "", "base"):
        scoped = {k: v for k, v in env.items() if k != "HERMES_NAMESPACE"}
        if value is not None:
            scoped["HERMES_NAMESPACE"] = value
        assert_namespace_isolation(live, env=scoped)


def test_store_root_fails_fast_when_a_namespaced_process_resolves_the_base(layout, monkeypatch):
    env, base, _, own = layout
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HERMES_HOME", str(own / "profiles" / "base"))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(own / "agent-runtime"))
    monkeypatch.delenv("HERMES_HEAD_HOME", raising=False)
    assert paths.store_root() == own / "agent-runtime"
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(base / "agent-runtime"))
    with pytest.raises(NamespaceIsolationViolation):
        paths.store_root()


def test_root_anchor_refuses_a_namespace_root(layout, tmp_path, monkeypatch):
    env, _, _, own = layout
    monkeypatch.setenv("HOME", str(tmp_path / "posix-home"))
    store = own / "agent-runtime"
    (store / "sessions").mkdir(parents=True)  # store-like, so only the namespace rule can refuse
    full = {**env, "HERMES_AGENT_RUNTIME_ROOT": str(store), "HERMES_HOME": str(own / "profiles" / "base")}
    report = publish_store_root_anchor(full, resolution=resolve_runtime(full))
    assert report.outcome is RootAnchorOutcome.NAMESPACED
    assert not (tmp_path / "appdata").exists()
