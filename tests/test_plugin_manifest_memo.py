"""The manifest memo hands out what the real parser would: fresh after an edit, a private copy, no cached failure."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.plugin_manifest_memo import _memoizing, clear_plugin_manifest_memo


@pytest.fixture
def counted(tmp_path):
    calls: list[Path] = []

    def real(manifest_file, plugin_dir, source, prefix):
        calls.append(Path(manifest_file))
        text = Path(manifest_file).read_text(encoding="utf-8")
        return None if text.startswith("broken") else {"name": text.strip(), "tags": ["a"]}

    clear_plugin_manifest_memo()
    yield _memoizing(real), calls
    clear_plugin_manifest_memo()


def _manifest(tmp_path: Path, text: str, mtime_ns: int) -> Path:
    path = tmp_path / "plugin.yaml"
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def test_an_unchanged_manifest_is_parsed_once_and_an_edited_one_again(tmp_path, counted):
    parse, calls = counted
    path = _manifest(tmp_path, "one", 1_000_000_000_000)
    assert parse(path, tmp_path, "bundled", "")["name"] == "one"
    assert parse(path, tmp_path, "bundled", "")["name"] == "one"
    assert len(calls) == 1
    path = _manifest(tmp_path, "two-longer", 2_000_000_000_000)
    assert parse(path, tmp_path, "bundled", "")["name"] == "two-longer"
    assert len(calls) == 2


def test_every_caller_gets_its_own_copy(tmp_path, counted):
    parse, _calls = counted
    path = _manifest(tmp_path, "one", 1_000_000_000_000)
    parse(path, tmp_path, "bundled", "")["tags"].append("mutated")
    assert parse(path, tmp_path, "bundled", "")["tags"] == ["a"]


def test_a_failed_parse_is_never_cached(tmp_path, counted):
    parse, calls = counted
    path = _manifest(tmp_path, "broken", 1_000_000_000_000)
    assert parse(path, tmp_path, "bundled", "") is None
    assert parse(path, tmp_path, "bundled", "") is None
    assert len(calls) == 2
