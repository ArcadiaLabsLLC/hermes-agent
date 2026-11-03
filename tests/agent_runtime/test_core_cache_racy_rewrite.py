"""RT-CORE-CACHE-SAME-TICK-REWRITE: a same-size rewrite inside one file-time tick is never served as current.

The input fingerprint's entries are ``(path, mtime_ns, size)``. A file rewritten to the same length before
the clock ticks keeps its triple, so — git's "racy" stat problem — a core built before the change would be
served as current. Git's answer, "smudged" entries: an entry whose mtime is within ``RACY_WINDOW_NS`` of the
walk's start is racy, the key records its bytes digest, the sidecar persists it, and a read whose stat digest
matches re-checks those bytes. The stat digest itself never includes them, so a later walk outside the window
still matches. Replayed deterministically by pinning the second write's mtime to the first's.
"""

from __future__ import annotations

import os

import pytest

from agent_runtime import core_cache
from agent_runtime.core_cache import fingerprint as fp
from tests._downstream import _seams


@pytest.fixture(autouse=True)
def fresh_cache_lane(monkeypatch):
    _seams.reset_core_cache_process_state()
    for module in (core_cache.fingerprint, core_cache.read, core_cache.persist):
        monkeypatch.setattr(module, "build_stamp_token", lambda: "probe:racy:clean")
    yield
    _seams.reset_core_cache_process_state()


def _baseline(root):
    baseline = root / "realm_sync" / "realm_x" / "office_baseline.json"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text('{"rev": 1}', encoding="utf-8")
    return baseline


def _rewrite_same_size_same_mtime(path, text):
    before = os.stat(path)
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = os.stat(path)
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)


def _core() -> dict:
    return {"parity": {"watermark": {"event_offset": 0}}}


def test_a_same_tick_same_size_rewrite_demotes_the_persisted_core(isolate_agent_runtime_root):
    """Mutation: drop the ``racy_contents_moved`` check in ``_judge_persisted_pair`` -> the stale core is served
    as matched, red."""
    baseline = _baseline(isolate_agent_runtime_root)
    key = core_cache.build_input_fingerprint()
    assert key is not None and str(baseline) in dict(key.racy)
    assert core_cache.write_back(_core(), fingerprint=key) is True
    _rewrite_same_size_same_mtime(baseline, '{"rev": 2}')
    _seams.reset_core_cache_process_state()
    read = core_cache.read_persisted_core()
    assert core_cache.build_input_fingerprint().digest == key.digest  # the stat digest cannot see it
    assert read.matched is False


def test_an_untouched_racy_store_still_matches_inside_and_outside_the_window(isolate_agent_runtime_root, monkeypatch):
    """The racy bytes never join the digest. Mutation: fold them into ``_fingerprint_over``'s digest -> the walk
    outside the window keys differently and the persisted core demotes, red."""
    _baseline(isolate_agent_runtime_root)
    key = core_cache.build_input_fingerprint()
    assert key.racy and core_cache.write_back(_core(), fingerprint=key) is True
    _seams.reset_core_cache_process_state()
    assert core_cache.read_persisted_core().matched is True
    monkeypatch.setattr(fp, "RACY_WINDOW_NS", -10**18)  # every mtime is now "old": nothing is racy
    _seams.reset_core_cache_process_state()
    later = core_cache.build_input_fingerprint()
    assert later.racy == () and later.digest == key.digest
    assert core_cache.read_persisted_core().matched is True
