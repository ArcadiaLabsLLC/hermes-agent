"""The ``missing_data`` rule form: fires on ATTESTED absence, ``unknown`` keeps its meaning
(plan ``planned/LENS_EXTENSIONS_2026-10-27.md`` §5 decisions 1, 2, 4; ``RT-LENS-MISSING-DATA-RULE``).

The corpus ``conformance/missing_data_corpus.json`` is hermes-authored (not one of Companion's pinned
files): one rule, a 5 s cadence, and per case the rows, the watch's start, ``now`` and the verdict.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, UTC
from pathlib import Path

import pytest

from agent_runtime.lens.episode import EpisodeState, observe
from agent_runtime.lens.feed import Observation
from agent_runtime.lens.manifest import read_manifest
from agent_runtime.lens.rules import ATTESTING_REASONS, NON_ATTESTING_REASONS, Verdict, evaluate, read_rule
from agent_runtime.lens.sources.transport import ReadReason
from agent_runtime.lens.wire_value import WireError

CORPUS = json.loads((Path(__file__).with_name("conformance") / "missing_data_corpus.json").read_text(encoding="utf-8"))
RULE = read_rule(CORPUS["rule"])
INTERVAL = timedelta(milliseconds=CORPUS["interval_ms"])
NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
CASES = {case["id"]: case for case in CORPUS["cases"]}


def _at(ms: int) -> datetime:
    return NOW + timedelta(milliseconds=ms)


def _verdict(case: dict, rule: dict = RULE) -> Verdict:
    observations = [
        Observation(monitor_id="m", feed_id="beat", sequence=i + 1, observed_at=_at(row["at_ms"]),
                    received_at=_at(row["at_ms"]), value=row["value"], gap=row["value"] is None, reason=row["reason"])
        for i, row in enumerate(case["rows"])
    ]
    return evaluate(rule, observations, now=_at(case["now_ms"]), expected_interval=INTERVAL, was_firing=False,
                    watched_since=_at(case["watched_since_ms"]), pushed=case["push"])


@pytest.mark.parametrize("case", CORPUS["cases"], ids=list(CASES))
def test_missing_data_corpus(case):
    assert _verdict(case).value == case["expected"]


def test_recovery_moves_the_episode_to_recovered():
    """Decision 4: the first valid current read after FIRING recovers the Episode; resolution is not ours."""

    opened = observe(monitor_id="m", rule_id="silent", next_ordinal=1,
                     verdict=_verdict(CASES["attested-absence-past-the-window-fires"]), at=_at(0))
    recovered = observe(monitor_id="m", rule_id="silent", next_ordinal=2, previous=opened, at=_at(5000),
                        verdict=_verdict(CASES["one-valid-read-after-firing-is-healthy"]))
    assert (opened.state, recovered.state, recovered.ordinal) == (EpisodeState.ACTIVE, EpisodeState.RECOVERED, 1)


def test_without_a_watch_start_absence_never_fires():
    case = CASES["attested-absence-past-the-window-fires"]
    assert _verdict({**case, "watched_since_ms": 0, "now_ms": 0}) is Verdict.UNKNOWN
    observations = [Observation(monitor_id="m", feed_id="beat", sequence=1, observed_at=_at(-1000),
                                received_at=_at(-1000), value=None, gap=True, reason="timeout")]
    assert evaluate(RULE, observations, now=_at(0), expected_interval=INTERVAL, was_firing=False) is Verdict.UNKNOWN


def test_every_gap_reason_is_classified_exactly_once():
    """Enumerated from ``ReadReason`` itself: a reason added later must be placed on one side."""

    carry_a_value = {"ok", "not_modified"}  # §2 decision 5's ``not_modified`` records the last value
    gaps = {reason.value for reason in ReadReason} - carry_a_value
    assert gaps <= ATTESTING_REASONS | NON_ATTESTING_REASONS, gaps - ATTESTING_REASONS - NON_ATTESTING_REASONS
    assert not ATTESTING_REASONS & NON_ATTESTING_REASONS


def _manifest(window_ms: int, **rule) -> dict:
    return {"version": 1, "monitor_id": "beats", "persona_id": None,
            "feeds": [{"version": 1, "id": "beat", "kind": "push", "interval_ms": 60000, "source": {}}],
            "rules": [{**CORPUS["rule"], "window_ms": window_ms, **rule}],
            "automation": {"level": "notify", "when": "always", "daily_turn_cap": 4}}


def test_the_window_must_cover_the_feeds_continuity_limit():
    assert read_manifest(_manifest(90000))["rules"][0]["form"] == "missing_data"
    with pytest.raises(WireError):
        read_manifest(_manifest(89999))


@pytest.mark.parametrize("bad", [
    {"direction": "above"}, {"threshold": 1, "recovery_threshold": 1}, {"recovery_threshold": 5},
    {"confirm_reads": 2}, {"samples": 2}, {"window_ms": 0}, {"window_ms": 24 * 60 * 60 * 1000 + 1},
])
def test_the_closed_form_refuses_what_absence_does_not_mean(bad):
    with pytest.raises(WireError):
        read_rule({**CORPUS["rule"], **bad})
