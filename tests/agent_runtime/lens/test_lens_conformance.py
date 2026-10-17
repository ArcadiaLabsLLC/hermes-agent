"""Lens L0 — Companion's Monitoring conformance corpus, replayed against the Python port.

The corpus files under ``conformance/`` are Companion's, copied byte-for-byte and
pinned by SHA-256 (``conformance/corpus_manifest.json``). They are input AND
oracle: never regenerate an expectation from this implementation. The fixture
defaults below are Companion's ``test/fixtures.dart`` (rule ``high`` on feed
``cpu``, above 80 / recover at 70, 5 s cadence, ``fixtureNow`` 2026-09-14 12:00Z),
and the corpus's camelCase rule overrides map onto the hermes snake_case schema.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

import pytest

from agent_runtime.lens.episode import Decision, Episode, EpisodeState, needs_admission, observe
from agent_runtime.lens.evidence import build_evidence
from agent_runtime.lens.feed import Observation
from agent_runtime.lens.rules import Verdict, evaluate, read_rule

CORPUS = Path(__file__).with_name("conformance")
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
INTERVAL = timedelta(seconds=5)

_CAMEL = {"windowMs": "window_ms", "recoveryThreshold": "recovery_threshold", "feedId": "feed_id"}
_FORMS = {"forDuration": "for_duration", "consecutiveSamples": "consecutive_samples"}
_STATES = {"closedRecovered": "closed_recovered"}


def _load(name: str):
    pins = json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8"))["files"]
    raw = (CORPUS / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == pins[name], f"{name} changed without review"
    return json.loads(raw)


def _rule(override: dict) -> dict:
    mapped = {_CAMEL.get(key, key): value for key, value in override.items()}
    if "form" in mapped:
        mapped["form"] = _FORMS.get(mapped["form"], mapped["form"])
    return read_rule({
        "version": 1, "id": "high", "feed_id": "cpu", "form": "threshold", "severity": "urgent",
        "direction": "above", "threshold": 80, "recovery_threshold": 70, "window_ms": 0, "samples": 1,
        **mapped,
    })


def _at(ms: int) -> datetime:
    return NOW + timedelta(milliseconds=ms)


def _sample(frames: list, index: int) -> Observation:
    frame = frames[index]
    return Observation(monitor_id="monitor-1", feed_id="cpu", sequence=index + 1,
                       observed_at=_at(frame.get("observedMs", frame["atMs"])), received_at=_at(frame["atMs"]),
                       value=float(frame["value"]))


def _samples_until(frames: list, index: int) -> list[Observation]:
    return [_sample(frames, i) for i in range(index + 1) if frames[i].get("sample") is not False]


def _episode_oracle(episode: Episode) -> dict:
    return {
        "rule": episode.rule_id, "state": episode.state.value, "ordinal": episode.ordinal, "count": episode.count,
        "firstMs": int((episode.first_seen - NOW) / timedelta(milliseconds=1)),
        "lastMs": int((episode.last_seen - NOW) / timedelta(milliseconds=1)),
        "decision": None if episode.decision is None else episode.decision.value,
    }


def _expected_episodes(oracle: dict) -> list[dict]:
    return [{**row, "state": _STATES.get(row["state"], row["state"])} for row in oracle["episodes"]]


OBSERVATIONS = _load("observation_corpus.json")


@pytest.mark.parametrize("case", OBSERVATIONS, ids=[case["id"] for case in OBSERVATIONS])
def test_observation_corpus_verdicts(case):
    """Contracts level: the evaluator alone (Companion ``observation_corpus_test.dart``)."""

    rules = [_rule(override) for override in case["rules"]]
    was_firing: dict[str, bool] = {}
    for index, frame in enumerate(case["frames"]):
        actual = {}
        for rule in rules:
            verdict = evaluate(rule, _samples_until(case["frames"], index), now=_at(frame["atMs"]),
                               expected_interval=INTERVAL, was_firing=was_firing.get(rule["id"], False))
            actual[rule["id"]] = verdict.value
            if verdict is not Verdict.UNKNOWN:
                was_firing[rule["id"]] = verdict is Verdict.FIRING
        assert actual == frame["oracle"]["verdicts"], f"{case['id']} frame {index}"


@pytest.mark.parametrize("case", OBSERVATIONS, ids=[case["id"] for case in OBSERVATIONS])
def test_observation_corpus_episodes(case):
    """Runtime level: evaluator + episode transition (Companion runtime ``observation_corpus_test.dart``)."""

    rules = [_rule(override) for override in case["rules"]]
    episodes: dict[str, Episode] = {}
    for index, frame in enumerate(case["frames"]):
        for rule in rules:
            previous = episodes.get(rule["id"])
            verdict = evaluate(rule, _samples_until(case["frames"], index), now=_at(frame["atMs"]),
                               expected_interval=INTERVAL,
                               was_firing=previous is not None and previous.state is EpisodeState.ACTIVE)
            nxt = observe(monitor_id="monitor-1", rule_id=rule["id"],
                          next_ordinal=(previous.ordinal if previous else 0) + 1,
                          verdict=verdict, at=_at(frame["atMs"]), previous=previous)
            if nxt is not None:
                episodes[rule["id"]] = nxt
        actual = sorted((_episode_oracle(e) for e in episodes.values()), key=lambda row: row["rule"])
        assert actual == _expected_episodes(frame["oracle"]), f"{case['id']} frame {index}"


REARM = _load("episode_rearm_corpus.json")


@pytest.mark.parametrize("case", REARM, ids=[case["id"] for case in REARM])
def test_episode_rearm_corpus(case):
    first = observe(monitor_id="monitor-1", rule_id="high", next_ordinal=1, verdict=Verdict.FIRING, at=NOW)
    suppressed = case["suppressedUntilMs"]
    episode = Episode(
        monitor_id=first.monitor_id, rule_id=first.rule_id, ordinal=first.ordinal,
        first_seen=first.first_seen, last_seen=_at(case["decisionAtMs"]), count=first.count,
        state=EpisodeState(_STATES.get(case["decisionState"], case["decisionState"])),
        suppressed_until=None if suppressed is None else _at(suppressed),
        turn_id="turn-1", decision=Decision(case["selection"]), decided_at=_at(case["decisionAtMs"]),
    )
    episode = Episode.from_json(json.loads(json.dumps(episode.to_json())))  # the replay starts from the wire
    admissions = 1
    for frame in case["frames"]:
        episode = observe(monitor_id="monitor-1", rule_id="high", next_ordinal=episode.ordinal + 1,
                          verdict=Verdict.FIRING, at=_at(frame["atMs"]), previous=episode)
        if needs_admission(episode, _at(frame["atMs"])):
            admissions += 1
        expected = {key: frame[key] for key in ("state", "ordinal", "count", "admissions")}
        expected["state"] = _STATES.get(expected["state"], expected["state"])
        assert {"state": episode.state.value, "ordinal": episode.ordinal, "count": episode.count,
                "admissions": admissions} == expected
        if episode.turn_id is None:
            episode = replace(episode, turn_id=f"turn-{admissions}")


EVIDENCE = _load("evidence_corpus.json")


@pytest.mark.parametrize("row", EVIDENCE, ids=[row["id"] for row in EVIDENCE])
def test_evidence_corpus(row):
    sources = [
        Observation(monitor_id="monitor-1", feed_id="cpu", sequence=i + 1, observed_at=NOW + timedelta(seconds=5 * i),
                    received_at=NOW + timedelta(seconds=5 * i), value=float(10 * (i + 1)))
        for i in range(3)
    ]
    window = build_evidence(sources, monitor_id="monitor-1", feed_ids=["cpu"],
                            start=_at(row["startMs"]), end=_at(row["endMs"]))
    assert [obs.sequence for obs in window.observations] == row["sequences"]
    assert [obs.value for obs in window.observations] == row["values"]
    assert window.gap_count == row["gapCount"]
