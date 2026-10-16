"""The scratch prune's process helpers tolerate an install without psutil."""

import os
import sys

import pytest

import hermes_constants_scratch as scratch


def test_own_lineage_without_psutil_is_empty(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert scratch._own_lineage() == set()


def test_reap_without_psutil_reaps_nothing(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert scratch.reap_processes_rooted_in(tmp_path, [tmp_path / "x"]) == 0


def test_own_lineage_with_psutil_contains_this_process():
    pytest.importorskip("psutil")
    assert os.getpid() in scratch._own_lineage()
