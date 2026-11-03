"""RT-CORE-CACHE-SAME-TICK-REWRITE: a same-size rewrite inside one file-time tick moves the digest.

The input fingerprint's entries are ``(path, mtime_ns, size)``. A file rewritten to the same length before
the clock ticks keeps its triple, so — git's "racy" stat problem — a core built before the change would be
served as current. An entry whose mtime is not older than the walk's start by ``RACY_WINDOW_NS`` is racy and
its bytes join the digest. Replayed deterministically by pinning the second write's mtime to the first's.
"""

from __future__ import annotations

import os

from agent_runtime import core_cache
from agent_runtime.core_cache import fingerprint as fp


def _rewrite_same_size_same_mtime(path, text):
    before = os.stat(path)
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = os.stat(path)
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)


def test_a_same_tick_same_size_rewrite_moves_the_digest(isolate_agent_runtime_root):
    """Mutation: drop the racy hashing (``_fingerprint_over(entries)`` without ``racy_contents``) -> the
    digest stays put across the rewrite, red."""
    baseline = isolate_agent_runtime_root / "realm_sync" / "realm_x" / "office_baseline.json"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text('{"rev": 1}', encoding="utf-8")
    first = core_cache.build_input_fingerprint()
    assert first is not None and str(baseline) in dict(first.racy)
    _rewrite_same_size_same_mtime(baseline, '{"rev": 2}')
    second = core_cache.build_input_fingerprint()
    assert second is not None and second.entries == first.entries
    assert second.digest != first.digest


def test_an_old_entry_is_not_racy_and_an_unchanged_racy_one_keeps_its_digest(isolate_agent_runtime_root, monkeypatch):
    """A settled store is keyed by stat alone; an unchanged racy store keys identically twice."""
    baseline = isolate_agent_runtime_root / "realm_sync" / "realm_x" / "office_baseline.json"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text('{"rev": 1}', encoding="utf-8")
    assert core_cache.build_input_fingerprint().digest == core_cache.build_input_fingerprint().digest
    monkeypatch.setattr(fp, "RACY_WINDOW_NS", -10**18)  # every mtime is older than the cutoff
    settled = core_cache.build_input_fingerprint()
    assert settled.racy == ()
    assert settled.digest == fp._fingerprint_over(settled.entries).digest


def test_a_refreshed_re_key_inside_the_window_still_matches_the_store(isolate_agent_runtime_root):
    """The post-build re-stat (IC-2) carries each kept / adopted entry's bytes digest. Mutation: re-key with
    ``_fingerprint_over(adopted.values())`` (no racy digests) -> the persisted key misses a fresh walk of the
    same store inside the window, red."""
    from tests._downstream import _seams
    from tests.agent_runtime.test_core_cache_post_build_restat import _core, _seed_store
    from utils import atomic_json_write

    _seams.reset_core_cache_process_state()
    row, _workspace = _seed_store(isolate_agent_runtime_root)
    key = core_cache.build_input_fingerprint()
    atomic_json_write(row, {"id": "inst_probe", "rev": 2})  # the build's own write: the re-stat adopts it
    assert core_cache.write_back(_core(), fingerprint=key) is True
    _seams.reset_core_cache_process_state()
    read = core_cache.read_persisted_core()
    assert read.matched is True, read.demote_reason
