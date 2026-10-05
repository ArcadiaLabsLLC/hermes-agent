"""The persisted core's build stamp keys on the CODE TREE, not the commit.

Plan ``turn-latency-h-turn1-2026-10-05.md`` stage D4: a vault-only commit moved
HEAD, the next boot read ``snapshot_core_cache … reason=build_stamp_mismatch``
and paid a 15 s cold core for code that had not changed.
"""

from __future__ import annotations

import pytest

from agent_runtime import build_stamp as build_stamp_module
from agent_runtime.build_stamp import BuildStamp
from agent_runtime.core_cache.fingerprint import build_stamp_token


def _stamp(*, commit="a" * 40, code_tree="c" * 40, dirty=False, source="git"):
    return BuildStamp(
        commit=commit,
        dirty=dirty,
        source=source,
        reason="",
        repo_root="/repo",
        resolved_at="2026-10-05T00:00:00Z",
        code_tree=code_tree,
        code_tree_reason="" if code_tree else "not_git:unknown",
    )


@pytest.fixture
def stamp_is(monkeypatch):
    def _set(stamp: BuildStamp) -> str | None:
        monkeypatch.setattr(build_stamp_module, "build_stamp", lambda: stamp)
        return build_stamp_token()

    return _set


def test_two_commits_with_one_code_tree_share_a_token_so_the_core_is_kept(stamp_is):
    before = stamp_is(_stamp(commit="a" * 40))
    after = stamp_is(_stamp(commit="b" * 40))

    assert before is not None
    assert before == after


def test_a_different_code_tree_is_a_different_token(stamp_is):
    assert stamp_is(_stamp(code_tree="c" * 40)) != stamp_is(_stamp(code_tree="d" * 40))


def test_dirt_still_moves_the_token(stamp_is):
    assert stamp_is(_stamp(dirty=False)) != stamp_is(_stamp(dirty=True))


def test_an_unmeasured_tree_falls_back_to_the_commit(stamp_is):
    one = stamp_is(_stamp(commit="a" * 40, code_tree=None, source="build_sha_file"))
    two = stamp_is(_stamp(commit="b" * 40, code_tree=None, source="build_sha_file"))

    assert one is not None and two is not None
    assert one != two


def test_no_commit_is_still_no_token(stamp_is):
    assert stamp_is(_stamp(commit=None)) is None
