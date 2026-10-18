"""tests/_downstream/parse_memo.py: a checkout YAML file parses once per test process."""

from __future__ import annotations

from pathlib import Path

from tests._downstream import parse_memo as memo

_LOCALE = Path(memo._REPO_ROOT) / "locales" / "en.yaml"


def _counting():
    calls = []

    def real(stream):
        calls.append(1)
        document = stream if isinstance(stream, str) else stream.read()
        return {"doc": document[:16], "nested": {"list": [1, 2]}}

    return calls, memo._memoized(real)


def test_a_checkout_file_parses_once_and_each_caller_gets_its_own_copy(monkeypatch):
    """Killing mutation: return ``real(stream)`` unconditionally in ``safe_load`` (every read parses)."""

    monkeypatch.setattr(memo, "_MEMO", {})
    calls, load = _counting()
    with _LOCALE.open(encoding="utf-8-sig") as handle:
        first = load(handle)
    first["nested"]["list"].append("mutated by a caller")
    with _LOCALE.open(encoding="utf-8-sig") as handle:
        second = load(handle)
    assert len(calls) == 1
    assert second["nested"]["list"] == [1, 2]


def test_temp_files_strings_and_offset_streams_always_parse(monkeypatch, tmp_path):
    """Killing mutation: drop the ``startswith(_REPO_ROOT)`` test in ``_bundled_key`` (a test home's
    file, rewritten at the same size inside one clock tick, would read stale)."""

    monkeypatch.setattr(memo, "_MEMO", {})
    calls, load = _counting()
    own = tmp_path / "config.yaml"
    own.write_text("a: 1\n", encoding="utf-8")
    for _ in range(2):
        with own.open(encoding="utf-8") as handle:
            load(handle)
        load("a: 1\n")
    with _LOCALE.open(encoding="utf-8-sig") as handle:
        handle.read(4)
        load(handle)
    assert len(calls) == 5


def test_a_changed_file_parses_again(monkeypatch):
    """The key carries the file's (mtime_ns, size): a different stamp is a miss."""

    monkeypatch.setattr(memo, "_MEMO", {})
    calls, load = _counting()
    with _LOCALE.open(encoding="utf-8-sig") as handle:
        load(handle)
    (key,) = memo._MEMO
    memo._MEMO[(key[0], key[1] - 1, key[2], key[3])] = memo._MEMO.pop(key)
    with _LOCALE.open(encoding="utf-8-sig") as handle:
        load(handle)
    assert len(calls) == 2
