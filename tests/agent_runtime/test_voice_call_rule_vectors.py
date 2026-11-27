"""RT-FU-ETERNIAS-AGENT-CALL-CAN-USE-HERMES-OWN-INTERRUPT-RULES: one file states hermes's voice-call rules.

``tests/fixtures/voice_call_rules/vectors.json`` is what the LIVE rules answer over named scenarios
(``tests/agent_runtime/_voice_call_rule_vectors.py``): the barge-in detector as ``full_duplex_listen`` builds it, the
own-voice check and the stop-phrase match. A client port (Eternia's agent call) is tested against the
same file, so these tests hold the file to the code, each scenario to what its name says, and the
served revision to the file.

Killing mutations (each watched red):
* ``tools/voice_mode.py`` ``PLAYBACK_MIN_TRIGGER = 1300.0`` -> the file no longer matches the live rules
  (and ``loud_speaker_bleed_alone_never_trips`` trips);
* ``_BargeDetector._track_playback`` gap ``> 33`` -> ``> 50``, or ``>= 33`` -> the re-arm scenarios move;
* ``full_duplex_listen`` grace ``grace_ms // 30`` -> ``(grace_ms + 29) // 30`` -> the file moves (the
  mapping is read from the live listener, never copied);
* the room window ``deque(maxlen=100)`` unbounded, or the ``SILENCE_RMS_THRESHOLD * 2`` clamp at ``* 1``
  -> the window and low-multiplier scenarios move;
* ``MIN_FRAGMENT_LENGTH_FOR_ECHO = 9`` -> the nine-character echo case flips;
* ``LinearPercentile`` without numpy's nearer-end branch -> the known-percentile case misses;
* ``RULE_VECTORS_REVISION`` one digit off -> the revision case.
"""

from __future__ import annotations

import hashlib
import random

import pytest

from agent_runtime.voice_call_rules import RULE_VECTORS_REVISION
from tests.agent_runtime import _voice_call_rule_vectors as vectors_script

VECTORS = vectors_script.VECTORS_PATH


def _vectors() -> dict:
    import json

    return json.loads(VECTORS.read_text(encoding="utf-8"))


def test_the_file_is_what_the_live_rules_answer():
    assert VECTORS.read_text(encoding="utf-8") == vectors_script.render(vectors_script.build()), (
        "the voice-call rules changed: run python -m tests.agent_runtime._voice_call_rule_vectors --write, move "
        "RULE_VECTORS_REVISION, and update every client port against the new file")


def test_the_file_is_the_same_without_numpy():
    """The vectors are written with numpy; a box without it checks them with LinearPercentile."""
    assert vectors_script.build(vectors_script.LinearPercentile) == _vectors()


@pytest.mark.parametrize(("values", "q", "expected"), [
    ([1, 2, 3, 4], 90, 3.7),  # rank 2.7: the nearer-end branch
    ([10, 20, 30, 40, 50], 90, 46.0),  # rank 3.6
    ([10, 20, 30, 40, 50], 30, 22.0),  # rank 1.2: the low-end branch
    ([5.0], 90, 5.0),
    ([200, 200, 200], 90, 200.0),
])
def test_the_numpy_free_percentile_matches_numpys_documented_answers(values, q, expected):
    assert vectors_script.LinearPercentile.percentile(values, q) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(("values", "numpys_answer"), [
    # numpy 2.4.6's exact answers where the plain a + (b - a) * t rounds differently: a port that
    # skips numpy's nearer-end branch moves a floor by one ulp and can move a trip by a block.
    ([3473.314, 1252.535], 3251.2361),
    ([435.03, 3042.536], 2781.7854),
])
def test_the_numpy_free_percentile_rounds_exactly_as_numpy_does(values, numpys_answer):
    assert vectors_script.LinearPercentile.percentile(values, 90) == numpys_answer


def test_the_numpy_free_percentile_is_numpys_bit_for_bit():
    np = pytest.importorskip("numpy", reason="numpy absent: the documented answers above still ran")
    rng = random.Random(20261127)
    for _ in range(500):
        values = [rng.uniform(0, 8000) for _ in range(rng.randint(1, 120))]
        q = rng.choice([90, 50, 10, rng.uniform(0, 100)])
        assert vectors_script.LinearPercentile.percentile(values, q) == float(np.percentile(values, q))


def test_the_served_revision_names_this_file():
    assert RULE_VECTORS_REVISION == hashlib.sha256(VECTORS.read_bytes()).hexdigest()[:16]


NEVER_TRIPS = {
    "quiet_room_never_trips", "loud_speaker_bleed_alone_never_trips", "a_cough_shorter_than_the_window_never_trips",
    "seven_of_ten_blocks_above_never_trips", "noisy_room_speech_under_the_cap_never_trips",
    "the_floor_follows_a_rising_room_while_nothing_plays",
    "speech_just_under_an_interpolated_trigger_is_taken_for_the_room",
    "a_low_multiplier_still_needs_twice_the_silence_level_so_this_never_trips",
}
TRIPS_WHILE_THE_AGENT_WORKS = {
    "speech_while_the_agent_works_trips_in_generation", "eight_of_ten_blocks_above_trips",
    "noisy_room_trigger_is_capped_so_speech_still_trips", "a_higher_multiplier_needs_louder_speech",
    "an_interpolated_floor_trips_just_above_its_trigger", "a_multiplier_of_zero_means_the_default",
    "the_room_level_forgets_blocks_older_than_its_window",
}
TRIPS_WHILE_THE_AGENT_SPEAKS = {
    "speech_over_the_reply_trips_in_playback", "playback_start_grace_holds_the_onset_then_trips",
    "no_grace_when_playback_resumes_inside_a_second", "grace_again_when_playback_resumes_after_a_second",
    "playback_before_calibration_ends_locks_the_floor_early", "zero_grace_trips_on_the_playback_onset",
    "no_grace_after_exactly_33_quiet_blocks", "grace_again_after_34_quiet_blocks",
}


def test_every_barge_scenario_shows_what_its_name_says():
    by_name = {case["name"]: case for case in _vectors()["barge_in"]}
    assert set(by_name) == NEVER_TRIPS | TRIPS_WHILE_THE_AGENT_WORKS | TRIPS_WHILE_THE_AGENT_SPEAKS, (
        "classify every scenario: a new one must say what it shows")
    for name in NEVER_TRIPS:
        assert by_name[name]["trip"]["block"] is None, name
    for name in TRIPS_WHILE_THE_AGENT_WORKS:
        assert by_name[name]["trip"]["phase"] == "generation", name
    for name in TRIPS_WHILE_THE_AGENT_SPEAKS:
        assert by_name[name]["trip"]["phase"] == "playback", name

    speech_start = 15 + 30 + 10 + 1  # calibrate, bleed, the quiet gap, then speech
    inside = by_name["no_grace_when_playback_resumes_inside_a_second"]["trip"]["block"]
    assert inside == speech_start + 7  # the eighth loud block: no grace held it
    after = by_name["grace_again_when_playback_resumes_after_a_second"]["trip"]["block"]
    assert after - (15 + 30 + 40 + 1) == 7 + 16  # the 500 ms grace held it 16 blocks
    # The boundary: 33 quiet blocks re-arm nothing, 34 re-arm the grace.
    assert by_name["no_grace_after_exactly_33_quiet_blocks"]["trip"]["block"] == (15 + 30 + 33 + 1) + 7
    assert by_name["grace_again_after_34_quiet_blocks"]["trip"]["block"] == (15 + 30 + 34 + 1) + 7 + 16
    # The window forgets: the trip lands after the 100 quiet blocks evicted the loud start.
    assert by_name["the_room_level_forgets_blocks_older_than_its_window"]["trip"]["block"] == 15 + 100 + 8
    assert by_name["zero_grace_trips_on_the_playback_onset"]["trip"]["block"] < \
        by_name["playback_start_grace_holds_the_onset_then_trips"]["trip"]["block"]
    # A 20x room needs 4000 (the ceiling): normal speech (3000, 30 blocks) never trips it.
    assert by_name["a_higher_multiplier_needs_louder_speech"]["trip"]["block"] > 15 + 30
    assert by_name["an_interpolated_floor_trips_just_above_its_trigger"]["trip"]["floor"] == 1020.0
    assert by_name["a_multiplier_of_zero_means_the_default"]["trip"] == \
        by_name["speech_while_the_agent_works_trips_in_generation"]["trip"]


def test_the_echo_and_stop_cases_show_what_their_names_say():
    data = _vectors()
    echo = {case["name"]: case["echo"] for case in data["echo"]}
    assert echo["the_whole_reply_heard_back"] and echo["a_fragment_of_a_long_reply"]
    assert echo["a_misheard_fragment_still_matches"]
    assert not echo["a_one_word_answer_inside_the_reply_is_the_user"]
    assert not echo["a_real_interruption_is_the_user"]
    assert not echo["a_nine_character_fragment_is_too_short_to_be_an_echo"]
    assert echo["a_ten_character_fragment_can_be_an_echo"]
    stop = {case["name"]: case["stop"] for case in data["stop_phrase"]}
    assert stop["the_default_phrase"] and stop["case_and_punctuation_do_not_matter"] and stop["a_configured_phrase"]
    assert not stop["a_sentence_starting_with_stop_is_sent"] and not stop["no_phrases_turns_stopping_off"]


def test_the_detector_settings_come_from_the_live_listener():
    """Grace 500 ms is 16 blocks and a zero multiplier is the default, as ``full_duplex_listen`` maps them."""
    from tools.voice_mode import DEFAULT_BARGE_MULTIPLIER

    params = vectors_script._detector_params({"threshold_multiplier": 0, "grace_ms": 500})
    assert params == {"mult": DEFAULT_BARGE_MULTIPLIER, "calib_blocks": 15, "trip_blocks": 10, "grace_blocks": 16}


def test_the_check_mode_says_when_the_file_is_stale(tmp_path, monkeypatch, capsys):
    stale = tmp_path / "vectors.json"
    stale.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(vectors_script, "VECTORS_PATH", stale)
    monkeypatch.setattr(vectors_script, "REPO_ROOT", tmp_path)
    assert vectors_script.main([]) == 1
    assert "stale" in capsys.readouterr().out
