"""The typed via: every decision reads the kind, never a spelling's first word.

Killing mutation: make ``kind_of`` answer ``None`` for an unknown spelling (what the
old first-word count did: the process silently counted as nothing) ->
``test_an_unknown_spelling_raises`` and ``test_the_ledger_counts_by_kind_not_by_first_word`` red.
"""

from __future__ import annotations

import pickle
import re

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


def test_the_runners_plugin_flags_are_no_hermes_flag_in_the_test_process_argv():
    """FH-RELAUNCH-TEST-SEES-THE-BUNDLE-RUNNER-PROFILE: the command the runner builds is the test
    process's ``sys.argv``, and ``hermes_cli.relaunch`` carries ``-p`` (hermes's profile flag) out of
    it. Killing mutation: ``plugin_flag`` returns ``"-p " + name`` split back into ``"-p", name`` at a
    call site (or any runner module spells a bare ``"-p"``) -> red here, and
    ``tests/hermes_cli/test_relaunch.py::TestRelaunch::test_calls_execvp`` red under the runner."""
    from pathlib import Path

    from hermes_cli import relaunch

    confirm = bundled._confirm
    built = [vias.plugin_flag("hermes_bundle_report"), "--hermes-bundle-events=x.jsonl", *confirm.PYTEST_ARGS]
    assert relaunch._extract_inherited_flags(built) == []
    scripts = Path(bundled.__file__).resolve().parent
    plugin_pair = re.compile(r'"-p",(?!\s*"-)')  # "-p" then its plugin; a flag table's "-p", "-o" is no pair
    bare = [p.name for p in sorted(scripts.glob("run_tests_bundled*.py")) if plugin_pair.search(p.read_text(encoding="utf-8"))]
    assert bare == [], f"spell pytest's plugin flag with run_tests_bundled_via.plugin_flag: {bare}"
