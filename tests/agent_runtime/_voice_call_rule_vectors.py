"""The shared test vectors for hermes's voice-call rules (RT-FU-ETERNIAS-AGENT-CALL-CAN-USE-HERMES-OWN-INTERRUPT-RULES).

A client that owns its own microphone (Eternia's agent call) cannot run hermes's listener, which opens
the device itself, so it ports three rules: the barge-in detector (``tools.voice_mode._BargeDetector``,
as ``full_duplex_listen`` builds it), the own-voice check (``tools.voice_mode_transcript.is_tts_echo``)
and the stop-phrase match (``is_voice_stop_phrase``). Hand-copied rules drift (the desktop app's
``voice-barge-in.ts`` already has), so every port is checked against ONE file: this script runs the
LIVE rules over the named scenarios below and writes what they answered, and
``tests/agent_runtime/test_voice_call_rule_vectors.py`` fails when the file and the live rules disagree.

    python -m tests.agent_runtime._voice_call_rule_vectors --write   # rewrite the file from the live rules
    python -m tests.agent_runtime._voice_call_rule_vectors           # exit 1 when the file is stale

It lives under ``tests/`` beside ``_serve_rpc_manifest.py`` (the same kind of producer) because it drives the
detector by its private name: no fork module may import an upstream ``_private`` name.

RMS values are int16 RMS of one 30 ms block, the detector's own scale; a port on another scale
converts (a 0-1 RMS times 32768). Each barge scenario is a list of ``[rms, playing, blocks]`` runs fed
one block at a time to a fresh detector, stopping at the first trip, as the listener does.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTORS_PATH = REPO_ROOT / "tests" / "fixtures" / "voice_call_rules" / "vectors.json"
FORMAT = 1
CMD = "python -m tests.agent_runtime._voice_call_rule_vectors --write"

#: The calibration (450 ms), grace (500 ms) and multiplier (3.0) are hermes's defaults; the scenarios
#: that change one say so in ``settings``.
DEFAULT_SETTINGS = {"threshold_multiplier": 3.0, "grace_ms": 500}

QUIET, BLEED_LOUD, SPEECH = 100, 1400, 3000
CALIBRATE = [QUIET, False, 15]  # 450 ms of quiet room before anything plays

BARGE_SCENARIOS: list[dict] = [
    {"name": "quiet_room_never_trips", "runs": [[QUIET, False, 80]]},
    {"name": "speech_while_the_agent_works_trips_in_generation", "runs": [CALIBRATE, [SPEECH, False, 20]]},
    {"name": "loud_speaker_bleed_alone_never_trips", "runs": [CALIBRATE, [BLEED_LOUD, True, 200]]},
    {"name": "speech_over_the_reply_trips_in_playback",
     "runs": [CALIBRATE, [900, True, 40], [SPEECH, True, 20]]},
    {"name": "playback_start_grace_holds_the_onset_then_trips",
     "runs": [CALIBRATE, [SPEECH, True, 40]]},
    {"name": "no_grace_when_playback_resumes_inside_a_second",
     "runs": [CALIBRATE, [900, True, 30], [QUIET, False, 10], [SPEECH, True, 30]]},
    {"name": "grace_again_when_playback_resumes_after_a_second",
     "runs": [CALIBRATE, [900, True, 30], [QUIET, False, 40], [SPEECH, True, 40]]},
    # The re-arm boundary itself: grace again only after MORE than 33 quiet blocks.
    {"name": "no_grace_after_exactly_33_quiet_blocks",
     "runs": [CALIBRATE, [900, True, 30], [QUIET, False, 33], [SPEECH, True, 30]]},
    {"name": "grace_again_after_34_quiet_blocks",
     "runs": [CALIBRATE, [900, True, 30], [QUIET, False, 34], [SPEECH, True, 40]]},
    # The room level keeps only its last 100 blocks: a loud start (floor 1000, trigger 3000) is
    # forgotten once 100 quiet ones follow, so 1000 then trips (floor 300, trigger 900).
    {"name": "the_room_level_forgets_blocks_older_than_its_window",
     "runs": [[1000, False, 15], [300, False, 100], [1000, False, 20]]},
    # A low multiplier never puts the trigger under twice the silence level (400): 1.5 x 200 = 300.
    {"name": "a_low_multiplier_still_needs_twice_the_silence_level_so_this_never_trips",
     "settings": {"threshold_multiplier": 1.5}, "runs": [CALIBRATE, [350, False, 30]]},
    {"name": "a_cough_shorter_than_the_window_never_trips",
     "runs": [CALIBRATE, [5000, False, 5], [QUIET, False, 40]]},
    {"name": "seven_of_ten_blocks_above_never_trips",
     "runs": [CALIBRATE] + [[SPEECH, False, 7], [QUIET, False, 3]] * 6},
    {"name": "eight_of_ten_blocks_above_trips",
     "runs": [CALIBRATE] + [[SPEECH, False, 8], [QUIET, False, 2]] * 3},
    {"name": "noisy_room_trigger_is_capped_so_speech_still_trips",
     "runs": [[2000, False, 15], [4500, False, 20]]},
    {"name": "noisy_room_speech_under_the_cap_never_trips",
     "runs": [[2000, False, 15], [3500, False, 60]]},
    {"name": "playback_before_calibration_ends_locks_the_floor_early",
     "runs": [[QUIET, False, 5], [900, True, 40], [SPEECH, True, 20]]},
    {"name": "the_floor_follows_a_rising_room_while_nothing_plays",
     "runs": [CALIBRATE, [250, False, 60], [550, False, 60], [1400, False, 30]]},
    {"name": "a_higher_multiplier_needs_louder_speech",
     "settings": {"threshold_multiplier": 20.0}, "runs": [CALIBRATE, [SPEECH, False, 30], [4500, False, 20]]},
    # A varied room: 15 distinct calibration blocks, 210..1050. The block that locks the floor is
    # also tracked once more, so 16 values put the 90th percentile halfway between 990 and 1050
    # (rank 13.5): floor 1020, trigger 3 x 1020 = 3060. Speech just under it is taken for the room.
    {"name": "an_interpolated_floor_trips_just_above_its_trigger",
     "runs": [[210 + 60 * i, False, 1] for i in range(15)] + [[3070, False, 20]]},
    {"name": "speech_just_under_an_interpolated_trigger_is_taken_for_the_room",
     "runs": [[210 + 60 * i, False, 1] for i in range(15)] + [[3050, False, 60]]},
    {"name": "zero_grace_trips_on_the_playback_onset",
     "settings": {"grace_ms": 0}, "runs": [CALIBRATE, [SPEECH, True, 20]]},
    {"name": "a_multiplier_of_zero_means_the_default",
     "settings": {"threshold_multiplier": 0}, "runs": [CALIBRATE, [SPEECH, False, 20]]},
]

ECHO_CASES: list[dict] = [
    {"name": "the_whole_reply_heard_back", "transcript": "Sure, here's a short story about a lighthouse.",
     "spoken": "Sure, here's a short story about a lighthouse."},
    {"name": "case_and_spacing_do_not_matter", "transcript": "  SURE,   here's a short STORY about a lighthouse ",
     "spoken": "Sure, here's a short story about a lighthouse."},
    {"name": "a_fragment_of_a_long_reply", "transcript": "the keeper climbed the stairs every night",
     "spoken": "Once upon a time there was a lighthouse by the sea. The keeper climbed the stairs every night "
               "to light the lamp, and the ships came home safely."},
    {"name": "a_misheard_fragment_still_matches", "transcript": "the keeper climbs the stair every night",
     "spoken": "Once upon a time there was a lighthouse by the sea. The keeper climbed the stairs every night "
               "to light the lamp, and the ships came home safely."},
    {"name": "a_one_word_answer_inside_the_reply_is_the_user", "transcript": "yes",
     "spoken": "Do you want another story? Say yes or no."},
    {"name": "a_real_interruption_is_the_user", "transcript": "wait, can you make it about a dragon instead",
     "spoken": "Once upon a time there was a lighthouse by the sea. The keeper climbed the stairs every night."},
    # The fragment search starts at 10 characters: 9 matching ones are too short to call an echo.
    {"name": "a_nine_character_fragment_is_too_short_to_be_an_echo", "transcript": "fox jumps",
     "spoken": "The quick brown fox jumps over the lazy dog by the river."},
    {"name": "a_ten_character_fragment_can_be_an_echo", "transcript": "fox jumpss",
     "spoken": "The quick brown fox jumps over the lazy dog by the river."},
    {"name": "an_empty_transcript_is_not_an_echo", "transcript": "", "spoken": "Hello there."},
    {"name": "nothing_spoken_means_no_echo", "transcript": "hello there", "spoken": ""},
    {"name": "a_transcript_longer_than_the_reply_is_not_a_fragment",
     "transcript": "hello there how are you doing today my friend", "spoken": "Hello there."},
]

STOP_CASES: list[dict] = [
    {"name": "the_default_phrase", "transcript": "stop", "phrases": ["stop"]},
    {"name": "case_and_punctuation_do_not_matter", "transcript": "  Stop! ", "phrases": ["stop"]},
    {"name": "a_sentence_starting_with_stop_is_sent", "transcript": "stop doing that and try again",
     "phrases": ["stop"]},
    {"name": "an_empty_transcript_is_not_a_stop", "transcript": "", "phrases": ["stop"]},
    {"name": "a_configured_phrase", "transcript": "Hang up.", "phrases": ["stop", "hang up"]},
    {"name": "no_phrases_turns_stopping_off", "transcript": "stop", "phrases": []},
]


class LinearPercentile:
    """numpy's default percentile (``method="linear"``), bit for bit, for a box without numpy.

    The detector's only numpy use is ``np.percentile(list, 90)``. The test venv ships no numpy, and
    hermes's own detector tests ``importorskip`` it, so without this the rule would be checked nowhere
    on such a box. ``tests/agent_runtime/test_voice_call_rule_vectors.py`` proves it equals numpy
    wherever numpy is installed; a client port implements this same formula.
    """

    @staticmethod
    def percentile(values, q: float) -> float:
        ordered = sorted(float(v) for v in values)
        rank = (len(ordered) - 1) * (float(q) / 100.0)
        low = int(rank // 1)
        high = min(low + 1, len(ordered) - 1)
        a, b, t = ordered[low], ordered[high], rank - low
        # numpy's _lerp: from the nearer end, so t == 1 lands exactly on b.
        return b - (b - a) * (1.0 - t) if t >= 0.5 else a + (b - a) * t


def percentile_backend():
    """Real numpy when installed, else :class:`LinearPercentile` (the vectors are the same either way)."""
    try:
        import numpy

        return numpy
    except ImportError:
        return LinearPercentile


class _Recorded(BaseException):
    """Stops ``full_duplex_listen`` once it has built its detector (BaseException: it catches Exception)."""


def _detector_params(settings: dict) -> dict:
    """The detector's arguments as the LIVE ``full_duplex_listen`` builds them for ``settings``.

    The listener is called with the settings as hermes's own callers pass them and a recording
    detector that stops it before it opens any device, so the mapping (milliseconds to blocks, a zero
    multiplier to the default) is the listener's own, never a copy here."""
    from tools import voice_mode

    seen: dict = {}

    def recording_detector(np, **kwargs):
        seen.update(kwargs)
        raise _Recorded

    real_import, real_detector = voice_mode._import_audio, voice_mode._BargeDetector
    voice_mode._import_audio = lambda: (None, percentile_backend())
    voice_mode._BargeDetector = recording_detector
    try:
        voice_mode.full_duplex_listen(lambda: True, multiplier=settings["threshold_multiplier"],
                                      grace_ms=settings["grace_ms"])
    except _Recorded:
        pass
    finally:
        voice_mode._import_audio, voice_mode._BargeDetector = real_import, real_detector
    if not seen:
        raise RuntimeError("full_duplex_listen no longer builds a _BargeDetector: the vectors cannot be written")
    return seen


def _run_barge(scenario: dict, np) -> dict:
    from tools.voice_mode import _BargeDetector

    settings = {**DEFAULT_SETTINGS, **scenario.get("settings", {})}
    detector = _BargeDetector(np, **_detector_params(settings))
    block = 0
    for rms, playing, count in scenario["runs"]:
        for _ in range(count):
            block += 1
            phase = detector.feed(float(rms), bool(playing))
            if phase is not None:
                return {"block": block, "phase": phase, "floor": round(detector.quiet_floor, 6)}
    return {"block": None, "phase": None, "floor": round(detector.quiet_floor, 6)}


def build(np=None) -> dict:
    """The vectors as the live rules answer them today (``np``: the percentile backend, default
    :func:`percentile_backend`)."""
    from tools import voice_mode
    from tools.voice_mode_transcript import (
        DEFAULT_TTS_ECHO_SIMILARITY_THRESHOLD,
        MIN_FRAGMENT_LENGTH_FOR_ECHO,
        is_tts_echo,
        is_voice_stop_phrase,
    )

    np = np or percentile_backend()
    listen = {name: p.default for name, p in inspect.signature(voice_mode.full_duplex_listen).parameters.items()}
    probe = voice_mode._BargeDetector(np, **_detector_params(DEFAULT_SETTINGS))
    return {
        "format": FORMAT,
        "about": "hermes's voice-call rules as the live code answers them; regenerate with "
                 "python -m tests.agent_runtime._voice_call_rule_vectors --write, never by hand. The constants are read from the live "
                 "code; the detector's inline literals (the floor's 90th percentile, the 33-block quiet gap "
                 "that re-arms the playback grace) are not constants there, so the scenarios pin them",
        "rules": {
            "barge_in": "tools/voice_mode.py _BargeDetector, built as full_duplex_listen builds it",
            "echo": "tools/voice_mode_transcript.py is_tts_echo",
            "stop_phrase": "tools/voice_mode_transcript.py is_voice_stop_phrase",
        },
        "use": [
            "one fresh detector per agent turn, armed when the user's message is sent, before any reply plays",
            "each 30 ms block: keep it in the pre-roll (the last pre_roll_ms of blocks), then feed its RMS "
            "and whether the agent's voice is playing; the first phase returned is the trip",
            "after a trip: stop the agent (its voice in playback, its turn in generation), then keep the "
            "pre-roll plus every following block until endpoint_silence_ms of blocks under "
            "silence_rms_threshold, or max_utterance_ms, and transcribe that",
            "the transcript: an exact stop phrase ends the call; else, for a playback trip only, an echo "
            "of the last whole reply spoken is dropped (hermes_cli/cli_voice_mixin.py "
            "_voice_submit_barge_utterance); else it is sent, marked interrupted",
        ],
        "constants": {
            "block_ms": 30,
            "sample_rate": voice_mode.SAMPLE_RATE,
            "silence_rms_threshold": voice_mode.SILENCE_RMS_THRESHOLD,
            "playback_min_trigger": voice_mode.PLAYBACK_MIN_TRIGGER,
            "trigger_ceiling": voice_mode.TRIGGER_CEILING,
            "default_threshold_multiplier": voice_mode.DEFAULT_BARGE_MULTIPLIER,
            "calibration_ms": listen["calibration_ms"],
            "sustained_ms": listen["sustained_ms"],
            "pre_roll_ms": listen["pre_roll_ms"],
            "endpoint_silence_ms": listen["endpoint_silence_ms"],
            "max_utterance_ms": listen["max_utterance_ms"],
            "floor_percentile_method": "linear",
            "trip_blocks_needed": probe.trip_needed,
            "trip_window_blocks": probe.recent_above.maxlen,
            "ambient_window_blocks": probe.ambient.maxlen,
            "echo_similarity_threshold": DEFAULT_TTS_ECHO_SIMILARITY_THRESHOLD,
            "echo_min_fragment_length": MIN_FRAGMENT_LENGTH_FOR_ECHO,
        },
        "default_settings": DEFAULT_SETTINGS,
        "barge_in": [
            {**scenario, "settings": {**DEFAULT_SETTINGS, **scenario.get("settings", {})}, "trip": _run_barge(scenario, np)}
            for scenario in BARGE_SCENARIOS
        ],
        "echo": [{**case, "echo": is_tts_echo(case["transcript"], case["spoken"])} for case in ECHO_CASES],
        "stop_phrase": [
            {**case, "stop": is_voice_stop_phrase(case["transcript"], tuple(case["phrases"]))} for case in STOP_CASES
        ],
    }


def render(vectors: dict) -> str:
    return json.dumps(vectors, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite the file (default: exit 1 when it is stale)")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(REPO_ROOT))
    text = render(build())
    if not args.write:
        current = VECTORS_PATH.read_text(encoding="utf-8") if VECTORS_PATH.exists() else ""
        if current != text:
            print(f"{VECTORS_PATH.relative_to(REPO_ROOT)} is stale: run {CMD}")
            return 1
        print("up to date")
        return 0
    VECTORS_PATH.parent.mkdir(parents=True, exist_ok=True)
    VECTORS_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {VECTORS_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
