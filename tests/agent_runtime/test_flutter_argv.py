"""The Flutter argv parser and ``FlutterCommand`` (plan ``build-running-work-2026-10-04.md`` §4, row H1).

One parser both the build guard and the recognizer read: a pin below holds that the guard
carries no token regex of its own, read off the RUNTIME module, not its spelling.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_runtime import flutter_build_guard
from agent_runtime.builds import flutter_argv as fa


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["flutter", "build", "windows", "--debug"], ("build", "windows", "debug", "flutter")),
        (["flutter.bat", "build", "apk"], ("build", "apk", "release", "flutter")),
        (["fvm", "flutter", "build", "windows", "--profile"], ("build", "windows", "profile", "flutter")),
        (["flutter", "-v", "run", "-d", "windows"], ("run", "run:windows", "debug", "flutter")),
        (["flutter", "run", "--release"], ("run", "run", "release", "flutter")),
        (["flutter", "pub", "get"], ("other", "", "", "flutter")),
        (
            [r"C:\flutter\bin\cache\dart-sdk\bin\dart.exe", "--packages=x", r"C:\flutter\bin\cache\flutter_tools.snapshot",
             "build", "windows", "--release"],
            ("build", "windows", "release", "flutter"),
        ),
        (["dart", "run", "tool/stagec_parity_build.dart", "--commit", "abc"], ("build", "qa_isolated", "release", "dart")),
        (["dart.exe", "language-server"], ("other", "", "", "dart")),
    ],
)
def test_an_argv_is_classified(argv, expected, tmp_path):
    recognition = fa.recognize_argv(argv, tmp_path)
    command = recognition.command
    assert command is not None and recognition.unrecognized_head == ""
    assert (command.kind, command.target, command.mode, command.toolchain) == expected
    assert command.project_dir == tmp_path


def test_an_unplaceable_head_is_the_toolchain_unrecognized_evidence(tmp_path):
    recognition = fa.recognize_argv(["python", "manage.py", "runserver"], tmp_path)
    assert recognition.command is None
    assert recognition.unrecognized_head == "python"
    assert fa.recognize_argv([], tmp_path).unrecognized_head == "(empty argv)"


def test_a_shell_line_moves_with_cd_and_the_build_segment_wins(tmp_path):
    line = f'cd "{tmp_path / "app"}" && flutter pub get && flutter build windows --release'
    recognition = fa.recognize_command(line, tmp_path)
    assert recognition.command is not None
    assert (recognition.command.kind, recognition.command.target) == ("build", "windows")
    assert recognition.command.project_dir == Path(str(tmp_path / "app"))
    # Positive control: with no build segment the last segment's answer stands.
    other = fa.recognize_command("flutter pub get", tmp_path)
    assert other.command is not None and other.command.kind == "other"


def test_the_guard_defines_no_token_regex_of_its_own():
    patterns = [name for name, value in vars(flutter_build_guard).items() if isinstance(value, re.Pattern)]
    assert patterns == []
    assert flutter_build_guard.flutter_builds is fa.flutter_builds
    # Positive control: the parser module DOES hold the patterns this pin looks for.
    assert any(isinstance(value, re.Pattern) for value in vars(fa).values())
