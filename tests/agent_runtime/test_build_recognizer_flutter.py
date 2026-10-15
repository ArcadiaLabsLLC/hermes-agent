"""The Flutter build recognizer over REAL transcripts (plan ``build-running-work-2026-10-04.md`` §4, row H2).

The four goldens under ``tests/fixtures/builds/`` were captured on this machine from a
scratch ``flutter create`` app (Flutter 3.41, Windows): ``flutter build windows --release``,
``--debug``, a release build with a planted unresolved external (LNK2019), and
``flutter run -d windows --no-resident`` after deleting ``.dart_tool/package_config.json``.
The project path in the failed-link golden is neutralised to ``C:\\work\\hb_scratch``.

When a Flutter release renames a phase, the ordered-sequence pin reds on the new golden
and the fix is one regex; until then the row says ``unknown`` for that stage and the new
wording is indexed as ``stage_line_unrecognized``.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from agent_runtime.builds import recognizer_flutter as rf
from agent_runtime.builds.unknowns import UNKNOWN_ARTIFACT_UNLOCATED, UNKNOWN_STAGE_LINE_UNRECOGNIZED

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "builds"
CWD = r"C:\work\hb_scratch"


def _golden(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("golden", "sequence", "artifact"),
    [
        ("flutter_build_windows_release", ["compiling", "done"], r"build\windows\x64\runner\Release\hb_scratch.exe"),
        ("flutter_build_windows_debug", ["compiling", "done"], r"build\windows\x64\runner\Debug\hb_scratch.exe"),
        ("flutter_build_failed_link", ["compiling", "linking"], None),
        ("flutter_run_windows", ["resolving", "compiling", "done"], r"build\windows\x64\runner\Debug\hb_scratch.exe"),
    ],
)
def test_each_real_transcript_produces_its_ordered_stage_sequence(golden, sequence, artifact):
    recognizer = rf.recognize_transcript(_golden(golden), cwd=CWD, seen_at=1.0)
    assert recognizer.sequence == sequence
    assert recognizer.stage == sequence[-1]
    expected = None if artifact is None else {"path": CWD + "\\" + artifact, "kind": "executable"}
    assert recognizer.artifact == expected
    # Every phase-shaped line in a real transcript is one the table knows.
    assert recognizer.unknowns.wire() == []


def test_a_build_ending_without_the_built_line_indexes_the_directories_probed():
    recognizer = rf.recognize_transcript(_golden("flutter_build_failed_link"), cwd=CWD, seen_at=1.0)
    recognizer.finish(target="windows", mode="release", seen_at=2.0)
    assert recognizer.artifact is None
    [entry] = recognizer.unknowns.wire()
    assert entry["kind"] == UNKNOWN_ARTIFACT_UNLOCATED
    assert "build/windows/x64/runner/Release" in entry["evidence"]
    # Positive control: a build that printed its Built line indexes nothing at finish.
    built = rf.recognize_transcript(_golden("flutter_build_windows_release"), cwd=CWD, seen_at=1.0)
    built.finish(target="windows", mode="release", seen_at=2.0)
    assert built.unknowns.wire() == []


def test_a_transcript_of_random_lines_is_unknown_throughout_and_indexes_nothing():
    rng = random.Random(20261004)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789 :-_=/[]"
    lines = ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 90))) for _ in range(400)]
    recognizer = rf.FlutterRecognizer(cwd=CWD)
    for line in lines:
        recognizer.line(line, seen_at=1.0)
        assert recognizer.stage == "unknown"
    assert recognizer.sequence == []
    assert recognizer.unknowns.wire() == []


def test_a_renamed_phase_indexes_exactly_that_line():
    renamed = _golden("flutter_build_windows_release").replace("Building Windows application...", "Assembling Windows application...")
    recognizer = rf.recognize_transcript(renamed, cwd=CWD, seen_at=5.0)
    assert recognizer.sequence == ["done"]
    [entry] = recognizer.unknowns.wire()
    assert entry["kind"] == UNKNOWN_STAGE_LINE_UNRECOGNIZED
    assert entry["evidence"] == "Assembling Windows application... 34.6s"


def test_the_stage_only_moves_forward():
    recognizer = rf.FlutterRecognizer(cwd=CWD)
    for line in ("Building Windows application...", "Resolving dependencies...", "√ Built build\\x.exe", "Syncing files to device Windows..."):
        recognizer.line(line, seen_at=1.0)
    assert recognizer.sequence == ["compiling", "done"]
    assert recognizer.stage_detail == "√ Built build\\x.exe"


def test_the_table_is_in_stage_order_one_regex_per_stage():
    stages = [stage for stage, _pattern in rf.FLUTTER_STAGES]
    assert len(stages) == len(set(stages))
    order = list(rf.BUILD_STAGES)
    assert stages == sorted(stages, key=order.index)
