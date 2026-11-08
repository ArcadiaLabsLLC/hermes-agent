import hashlib

from agent_runtime import parse_cache
from agent_runtime.parse_cache import (
    cached_by_mtime,
    cached_file_sha256,
    cached_yaml_file,
    clear_parse_cache,
)


def test_cached_yaml_file_parses_and_memoizes_by_mtime(tmp_path, monkeypatch):
    monkeypatch.setattr(parse_cache, "RACY_STAMP_NS", 0)  # a file written a moment ago; the window is proved below
    clear_parse_cache()
    path = tmp_path / "config.yaml"
    path.write_text("agent_runtime:\n  store_root: /some/where\n", encoding="utf-8")

    calls = {"n": 0}

    def loader(p):
        calls["n"] += 1
        from agent_runtime import yaml_io

        return yaml_io.load(p.read_text(encoding="utf-8"))

    first = cached_by_mtime(path, loader)
    second = cached_by_mtime(path, loader)
    assert first == {"agent_runtime": {"store_root": "/some/where"}}
    assert second is first  # same cached object
    assert calls["n"] == 1  # parsed once

    # A content change (new mtime) invalidates the entry.
    path.write_text("agent_runtime:\n  store_root: /elsewhere\n", encoding="utf-8")
    third = cached_by_mtime(path, loader)
    assert third == {"agent_runtime": {"store_root": "/elsewhere"}}
    assert calls["n"] == 2


def test_cached_yaml_file_missing_returns_default(tmp_path):
    clear_parse_cache()
    assert cached_yaml_file(tmp_path / "absent.yaml", default={}) == {}


def test_cached_file_sha256_matches_hashlib_and_caches(tmp_path):
    clear_parse_cache()
    path = tmp_path / "blob.bin"
    path.write_bytes(b"hello world" * 1000)
    expected = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    assert cached_file_sha256(path) == expected
    assert cached_file_sha256(path) == expected  # cache hit, same value


# RT-PARSE-CACHE-SAME-TICK-REWRITE: a same-size rewrite inside one filesystem clock tick keeps the stamp
# (Windows ~15.6 ms; ctime is creation time there). The stamp is pinned here so the rewrite shares it.
_T = 1_800_000_000_000_000_000


def _pinned(monkeypatch, path, *, now_ns):
    monkeypatch.setattr(parse_cache, "_stamp", lambda p: (str(p), 1, 2, _T, _T, 9))
    monkeypatch.setattr(parse_cache, "_now_ns", lambda: now_ns)
    clear_parse_cache()
    path.write_text("knob: 1\n", encoding="utf-8")
    assert cached_yaml_file(path) == {"knob": 1}
    path.write_text("knob: 2\n", encoding="utf-8")  # same size, same pinned stamp
    return cached_yaml_file(path)


def test_a_same_tick_rewrite_is_read_not_served_from_the_memo(tmp_path, monkeypatch):
    assert _pinned(monkeypatch, tmp_path / "config.yaml", now_ns=_T + 1_000_000) == {"knob": 2}


def test_a_stamp_older_than_the_window_is_memoized(tmp_path, monkeypatch):
    # The positive control: past the window the stamp is trusted (a rewrite would carry a newer one).
    assert _pinned(monkeypatch, tmp_path / "config.yaml", now_ns=_T + parse_cache.RACY_STAMP_NS) == {"knob": 1}


def test_a_racy_hash_is_not_memoized(tmp_path, monkeypatch):
    monkeypatch.setattr(parse_cache, "_stamp", lambda p: (str(p), 1, 2, _T, _T, 5))
    monkeypatch.setattr(parse_cache, "_now_ns", lambda: _T + 1_000_000)
    clear_parse_cache()
    path = tmp_path / "blob.bin"
    path.write_bytes(b"first")
    cached_file_sha256(path)
    path.write_bytes(b"secnd")
    assert cached_file_sha256(path) == "sha256:" + hashlib.sha256(b"secnd").hexdigest()
