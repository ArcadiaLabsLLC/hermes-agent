"""``_removal_walk``: the shared import index the removal gates read.

The gates (s27, s29, s49, s50) assert ABSENCE — "no production file imports
X" — so a walk that silently returned nothing would keep them green forever.
These tests pin the index itself: what it extracts, that an edited file is
re-read, and that the persisted store is used, keyed and discarded correctly.
"""

from __future__ import annotations

import pytest

from tests.agent_runtime import _removal_walk

_SOURCE = '''\
import os
import agent_runtime.snapshot as snap
from agent_runtime import operator_control
from . import sibling


def later():
    from agent_runtime.snapshot import build_snapshot
    snap.build_snapshot()
    sibling.helper()
    os.path.join("a", "b")
    return build_snapshot
'''


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    store = tmp_path / "store"
    monkeypatch.setattr(_removal_walk, "cache_dir", lambda: store)
    _removal_walk.clear_memory()
    yield store
    _removal_walk.clear_memory()


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_every_import_form_is_extracted_at_any_depth(tmp_path):
    path = _write(tmp_path, "mod.py", _SOURCE)

    record = _removal_walk.index([path])[str(path)]

    forms = {(r.kind, r.module, r.level, tuple(a.name for a in r.names)) for r in record.imports}
    assert forms == {
        ("import", None, 0, ("os",)),
        ("import", None, 0, ("agent_runtime.snapshot",)),
        ("from", "agent_runtime", 0, ("operator_control",)),
        ("from", None, 1, ("sibling",)),
        ("from", "agent_runtime.snapshot", 0, ("build_snapshot",)),
    }
    loads = {(bound, attr) for bound, attr, _line in record.attribute_loads}
    # First-party bindings are read; ``os`` is not first-party and is not.
    assert ("snap", "build_snapshot") in loads and ("sibling", "helper") in loads
    assert not any(bound == "os" for bound, _attr in loads)
    assert record.decode_ok is True


def test_a_file_that_does_not_parse_is_none_and_non_utf8_is_flagged(tmp_path):
    broken = _write(tmp_path, "broken.py", "def (:\n")
    latin = tmp_path / "latin.py"
    latin.write_bytes(b"x = '\xe9'\n")

    records = _removal_walk.index([broken, latin])

    assert records[str(broken)] is None
    assert records[str(latin)].decode_ok is False


def test_an_edited_file_is_re_read(tmp_path):
    path = _write(tmp_path, "mod.py", "import os\n")
    first = _removal_walk.index([path])[str(path)]

    path.write_text("from agent_runtime import operator_control\n", encoding="utf-8")
    second = _removal_walk.index([path])[str(path)]

    assert [r.kind for r in first.imports] == ["import"]
    assert [(r.kind, r.names[0].name) for r in second.imports] == [("from", "operator_control")]


def test_a_later_process_reads_the_persisted_store_instead_of_parsing(tmp_path, monkeypatch):
    path = _write(tmp_path, "mod.py", _SOURCE)
    expected = _removal_walk.index([path])[str(path)]

    _removal_walk.clear_memory()  # a fresh process
    monkeypatch.setattr(_removal_walk, "_extract", lambda _p: pytest.fail("re-parsed a stored file"))

    assert _removal_walk.index([path])[str(path)] == expected


def test_a_store_written_by_another_extractor_is_discarded(tmp_path, monkeypatch):
    path = _write(tmp_path, "mod.py", "import os\n")
    _removal_walk.index([path])

    _removal_walk.clear_memory()
    monkeypatch.setattr(_removal_walk, "_KEY", "another-extractor")
    parsed: list[str] = []
    real = _removal_walk._extract
    monkeypatch.setattr(_removal_walk, "_extract", lambda p: parsed.append(p) or real(p))

    _removal_walk.index([path])

    assert parsed == [str(path)]
