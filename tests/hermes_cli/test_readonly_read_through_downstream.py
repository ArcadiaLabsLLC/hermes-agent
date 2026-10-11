"""Positive controls for the computed ``load_config_readonly`` read-through (plan D3.06).

``tests/_downstream/conftest_plugin.py::_config_reads_through_load_config`` routes the
readonly loader through a PATCHED ``load_config`` for test files that import a reader the
fork moved (``tests/_downstream/fork_readonly_readers.py``). This file imports one
(``tools.vision_tools``), so the live arms below run under the route.
"""

from __future__ import annotations

import functools
import types
from pathlib import Path

import hermes_cli.config as config_module
import tools.vision_tools  # noqa: F401 — a fork-moved reader: puts this file under the route

from tests._downstream import fork_readonly_readers as readers
from tests._downstream.conftest_plugin import _deferring_readonly

REPO = Path(__file__).resolve().parents[2]


def test_a_patched_load_config_reaches_load_config_readonly(monkeypatch):
    monkeypatch.setattr(config_module, "load_config", lambda: {"source": "patch"})
    assert config_module.load_config_readonly() == {"source": "patch"}


def test_an_unpatched_load_config_leaves_the_readonly_path_alone(monkeypatch):
    calls = []
    original = config_module.load_config

    @functools.wraps(original)
    def spy():  # keeps the definition's identity: counts as unpatched
        calls.append(1)
        return original()

    monkeypatch.setattr(config_module, "load_config", spy)
    config_module.load_config_readonly()
    assert calls == [], "an unpatched load_config must not be read by load_config_readonly"


def test_the_deferral_needs_both_the_patch_and_a_selected_file():
    fake = types.ModuleType("fake_config")

    def load_config():
        return {"source": "disk"}

    load_config.__module__, load_config.__qualname__ = fake.__name__, "load_config"
    fake.load_config = load_config
    selected = _deferring_readonly(fake, lambda: {"source": "readonly"}, __file__)
    unselected = _deferring_readonly(
        fake, lambda: {"source": "readonly"}, str(REPO / "tests/scripts/test_upstream_footprint.py"))
    assert selected() == unselected() == {"source": "readonly"}  # WHEN: not patched
    fake.load_config = lambda: {"source": "patch"}
    assert selected() == {"source": "patch"}
    assert unselected() == {"source": "readonly"}  # WHICH: the file reaches no moved reader


def test_the_reader_set_is_read_from_the_ledger():
    derived = readers.fork_readonly_readers()
    assert {"tools.vision_tools", "plugins.dashboard_auth._shared"} <= derived
    assert "hermes_cli.config" not in derived, "the loader's own module would make the route a blanket"
    row = "| `tools/x.py` | 1 | 1 | carry | the FAL {} | S3 |"
    assert readers.readers_from_ledger(row.format(readers.READER_MOVED)) == {"tools.x"}
    assert readers.readers_from_ledger(row.format("read through load_config_readonly")) == frozenset()


def test_one_hop_of_the_import_graph_selects_the_files():
    # test_nous_provider imports plugins.dashboard_auth.nous, which imports the reader _shared.
    assert readers.file_reads_through(str(REPO / "tests/plugins/dashboard_auth/test_nous_provider.py"))
    assert readers.file_reads_through(str(REPO / "tests/tools/test_browser_console.py"))
    assert not readers.file_reads_through(str(REPO / "tests/scripts/test_upstream_footprint.py"))
