"""The namespace root's length budget (row RT-NAMESPACE-PATH-BUDGET).

``ROOT_BUDGET`` is ``MAX_PATH_CHARS`` less the longest path ``agent_runtime/paths.py`` builds below a
namespace root. This file re-measures that suffix from the module itself — every public function
that returns a path, called with 32-character ids — so a new, longer store path reds here instead of
failing on a player's disk.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

from agent_runtime import paths
from hermes_cli import _namespace_bootstrap as ns

ID = "i" * 32  # a uuid4 hex: the representative id length the budget is measured at
_STORE_ROOT_ARGS = {"gateway_dir", "install_record_path"}


def _fake_root(length: int) -> str:
    anchor = "C:\\" if sys.platform == "win32" else "/"
    return anchor + "r" * (length - len(anchor))


def _every_store_path(root: str, monkeypatch) -> dict[str, str]:
    """name -> the path each public ``paths`` builder returns under ``root``."""
    store = str(Path(root) / ns.STORE_DIRNAME)
    monkeypatch.delenv("HERMES_NAMESPACE", raising=False)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", store)
    out: dict[str, str] = {}
    for name, fn in inspect.getmembers(paths, inspect.isfunction):
        if fn.__module__ != paths.__name__ or name.startswith("_"):
            continue
        if name in _STORE_ROOT_ARGS:
            out[name] = str(fn(store))
            continue
        if "Path" not in str(inspect.signature(fn).return_annotation):
            continue
        params = list(inspect.signature(fn).parameters.values())
        if any("Path" in str(p.annotation) for p in params):
            continue  # a helper over a caller's path (unlink_quietly …), not a store builder
        out[name] = str(fn(*[ID for _ in params]))
    return out


def test_every_store_path_fits_max_path_under_a_budget_length_root(monkeypatch):
    built = _every_store_path(_fake_root(ns.ROOT_BUDGET), monkeypatch)
    assert len(built) > 80  # positive control: the walk found the builders, not an empty module
    too_long = {name: len(p) for name, p in built.items() if len(p) > ns.MAX_PATH_CHARS}
    assert too_long == {}


def test_the_budget_is_the_measured_longest_suffix(monkeypatch):
    root = _fake_root(ns.ROOT_BUDGET)
    longest = max(len(p) - len(root) for p in _every_store_path(root, monkeypatch).values())
    assert longest == ns.LONGEST_STORE_SUFFIX
    assert ns.ROOT_BUDGET == ns.MAX_PATH_CHARS - ns.LONGEST_STORE_SUFFIX


def _env_with_root_length(tmp_path: Path, length: int) -> tuple[dict[str, str], str]:
    stem = str(tmp_path / "n")
    folder = Path(stem + "p" * (length - len(stem) - 2))  # + separator + the one-character id
    assert len(str(folder / "x")) == length
    return {"HERMES_DEPENDENCY_ROOT": str(tmp_path / ".hermes"), "HERMES_NAMESPACES_DIR": str(folder)}, "x"


def test_a_root_over_the_budget_refuses_unless_long_paths_are_enabled(tmp_path: Path):
    if len(str(tmp_path / "n" / "x")) >= ns.ROOT_BUDGET:
        pytest.skip("tmp_path alone exceeds the budget on this box")
    env, at = _env_with_root_length(tmp_path, ns.ROOT_BUDGET)
    assert ns.layout(at, env, long_paths=False).root_length == ns.ROOT_BUDGET
    env, over = _env_with_root_length(tmp_path, ns.ROOT_BUDGET + 1)
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.layout(over, env, long_paths=False)
    assert caught.value.reason is ns.Reason.ROOT_TOO_LONG
    assert ns.layout(over, env, long_paths=True).root_length == ns.ROOT_BUDGET + 1


def test_probe_reports_the_root_length_and_the_budget(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: False)
    env = {"HERMES_DEPENDENCY_ROOT": str(tmp_path / ".hermes")}
    out = ns.probe(env, "acct-0123456789abcdef")
    assert out["root_length"] == len(str(tmp_path / "hermes-namespaces" / "acct-0123456789abcdef"))
    assert out["root_budget"] == ns.ROOT_BUDGET and out["max_path"] == ns.MAX_PATH_CHARS
    assert out["long_paths"] is False
    expected = None if out["root_length"] <= ns.ROOT_BUDGET else "namespace_root_too_long"
    assert (out["refusal"] or {}).get("reason") == expected
