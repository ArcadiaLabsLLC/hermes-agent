"""``pm._fork_default_extras``: the Developer Edition's default selection carries the provider SDKs.

Owner ruling 2026-10-15 (wave w1015c-dev): first setup installs ``all`` plus every provider SDK
the Launcher's Connections offers, from ONE fork-owned list read by setup / ``pm install``
(``pm.install._target_selection``) and the test environment default; upstream's ``all`` is never
edited; an existing environment missing one gets it at its next sync.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PYPROJECT = (
    '[project]\nname="dev"\nversion="1"\n'
    '[project.optional-dependencies]\nall=[]\nfal=[]\nanthropic=[]\nbedrock=[]\nvertex=[]\n'
    'azure-identity=[]\n'
)


@pytest.fixture
def install(tmp_path, monkeypatch):
    from pm import paths
    from pm.packages import Venv

    monkeypatch.delenv("HERMES_DISABLE_LAZY_INSTALLS", raising=False)
    root = tmp_path / "hermes"
    root.mkdir()
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    store = tmp_path / "tools"
    store.mkdir()
    monkeypatch.setattr(paths, "repo_root", lambda: root)
    monkeypatch.setattr(paths, "store_root", lambda: store)
    monkeypatch.setattr(Venv, "expected_stamp",
                        lambda self, extras, plugin_dirs=None: "stamp:" + ",".join(sorted(extras)))
    return Venv(root)


def _select(package, recorded, *, extras=None, shipped=None, repair=False):
    from pm.install import _target_selection

    fact = {"stamp": "old", "extras": recorded} if recorded is not None else {}
    return _target_selection(package, fact, extras=extras, inputs={"plugin_dirs": []},
                             repair=repair, shipped=shipped, frozen=None)


def test_the_list_is_the_connections_provider_extras_and_upstream_all_is_untouched():
    from hermes_cli.runtime_environment import _PM_EXTRA_FOR_DISTRIBUTION
    from pm._fork_default_extras import DEFAULT_EXTRAS, PROVIDER_SDK_EXTRAS

    assert set(PROVIDER_SDK_EXTRAS) == set(_PM_EXTRA_FOR_DISTRIBUTION.values())
    assert PROVIDER_SDK_EXTRAS[0] == "anthropic"
    assert DEFAULT_EXTRAS == ("all", *PROVIDER_SDK_EXTRAS)
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        declared = tomllib.load(handle)["project"]["optional-dependencies"]
    assert all(extra in declared for extra in PROVIDER_SDK_EXTRAS)
    assert not any(f"[{extra}]" in member for extra in PROVIDER_SDK_EXTRAS for member in declared["all"])


def test_the_test_environment_default_reads_the_same_list():
    from pm._fork_default_extras import DEFAULT_EXTRAS
    from pm.testenv import DEFAULT_TEST_EXTRAS

    assert DEFAULT_TEST_EXTRAS == DEFAULT_EXTRAS


def test_first_setup_selects_all_plus_the_provider_sdks(install):
    """``hermes pm install`` (and so setup) syncs ``["all"]`` into an empty ledger."""
    enabled, stamp, _ = _select(install, None, extras=["all"])
    assert enabled == ["all", "anthropic", "azure-identity", "bedrock", "vertex"]
    assert stamp == "stamp:all,anthropic,azure-identity,bedrock,vertex"


def test_an_existing_environment_missing_one_gets_it_at_the_next_sync(install):
    """``hermes update`` syncs with no extras: the recorded selection is widened."""
    enabled, stamp, _ = _select(install, ["all", "anthropic", "fal"])
    assert enabled == ["all", "anthropic", "azure-identity", "bedrock", "fal", "vertex"]
    assert stamp != "old"


def test_a_complete_selection_is_left_as_it_is(install):
    recorded = ["all", "anthropic", "azure-identity", "bedrock", "vertex"]
    assert _select(install, recorded)[0] == recorded


@pytest.mark.parametrize("case", ["bundled", "minimal", "repair", "lazy-off"])
def test_bundles_minimal_selections_repairs_and_the_hermetic_harness_are_not_widened(install, monkeypatch, case):
    if case == "bundled":
        enabled = _select(install, None, extras=["all"], shipped=["all"])[0]
    elif case == "minimal":
        enabled = _select(install, ["fal"])[0]
    elif case == "repair":
        enabled = _select(install, ["all"], repair=True)[0]
    else:
        monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")
        enabled = _select(install, ["all"])[0]
    assert "anthropic" not in enabled


def test_an_extra_the_tree_no_longer_declares_is_not_added(install):
    (install.project_root() / "pyproject.toml").write_text(PYPROJECT.replace("vertex=[]\n", ""), encoding="utf-8")
    assert "vertex" not in _select(install, ["all"])[0]
