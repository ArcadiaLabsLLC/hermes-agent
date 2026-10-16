"""The typed via: every decision reads the kind, never a spelling's first word.

Killing mutation: make ``kind_of`` answer ``None`` for an unknown spelling (what the
old first-word count did: the process silently counted as nothing) ->
``test_an_unknown_spelling_raises`` and ``test_the_ledger_counts_by_kind_not_by_first_word`` red.
"""

from __future__ import annotations

import pickle

import pytest

from scripts import run_tests_bundled as bundled  # registers the siblings below

import run_tests_bundled_plan as plan
import run_tests_bundled_via as vias


def test_a_via_spells_as_before_and_carries_its_kind():
    shard = vias.Via.shard(1, 4)
    assert shard == "shard 1/4" and shard.kind is vias.ViaKind.SHARD
    assert vias.Via.shards(4) == "4 shards" and vias.KNOWN_RED_SKIPPED == "known-red, skipped"
    assert pickle.loads(pickle.dumps(shard)).kind is vias.ViaKind.SHARD


@pytest.mark.parametrize("spelling, kind", [
    ("bundle", vias.ViaKind.BUNDLE),
    ("known-red, skipped", vias.ViaKind.KNOWN_RED_SKIPPED),
    ("shard 0/3", vias.ViaKind.SHARD),
    ("3 shards", vias.ViaKind.SHARDS),
    ("cached; green 2026-10-16 1.0s", vias.ViaKind.CACHED),
])
def test_a_bare_spelling_is_read_once_by_kind_of(spelling, kind):
    assert vias.kind_of(spelling) is kind


def test_an_unknown_spelling_raises():
    with pytest.raises(ValueError, match="unknown via"):
        vias.kind_of("shardish")


def test_the_ledger_counts_by_kind_not_by_first_word():
    ledger = plan.RunLedger(started=0.0, ended=10.0)
    ledger.processes = [
        plan.Process(vias.KNOWN_RED_SKIPPED, ["a"], 0, 1),
        plan.Process(vias.KNOWN_RED, ["b"], 0, 1),
        plan.Process(vias.Via.shard(0, 2), ["c"], 0, 1),
        plan.Process(vias.Via.shard(1, 2), ["c"], 0, 1),
        plan.Process(vias.RERUN, ["d"], 0, 1),
    ]
    counts = ledger.summary(2)["processes"]
    assert counts["known-red"] == 1 and counts["shard"] == 2 and counts["rerun"] == 1
    ledger.processes.append(plan.Process("bundel", ["e"], 0, 1))
    with pytest.raises(ValueError, match="unknown via"):
        ledger.summary(2)
