"""The Flutter argv parser: which ``flutter`` command a shell line runs, and where.

Lifted whole from ``agent_runtime.flutter_build_guard`` (plan
``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §4) so the guard
and the build recognizer read ONE parser: ``flutter``/``flutter.bat``/``flutter.exe``/
``fvm flutter``, the launch prefixes in front of the command word, and a ``cd`` /
``Set-Location`` / ``pushd`` segment that moves the directory the way the shell would.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from agent_runtime.builds.vocabulary import TOOLCHAIN_DART, TOOLCHAIN_FLUTTER

__layer__ = "models"


_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;\n|]")
_TOKEN_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')
_FLUTTER_NAMES = frozenset({"flutter", "flutter.bat", "flutter.exe"})
_CD_NAMES = frozenset({"cd", "chdir", "pushd", "set-location", "sl", "push-location"})
_PREFIX_WORDS = frozenset({"&", "call", "fvm", "exec", "command"})
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_MODES = ("debug", "profile", "release")


@dataclass(frozen=True)
class FlutterBuild:
    """One direct ``flutter build`` segment: where it runs and what it writes."""

    project_dir: Path
    target: str
    mode: str


def _tokens(segment: str) -> list[str]:
    return [token.strip("\"'") for token in _TOKEN_RE.findall(segment)]


def _command_words(tokens: list[str]) -> list[str]:
    """Drop the launch prefixes in front of the real command word."""

    words = list(tokens)
    while words:
        head = os.path.basename(words[0]).lower()
        if head in _PREFIX_WORDS or _ENV_ASSIGN_RE.match(words[0]):
            words = words[1:]
        elif head in ("cmd", "cmd.exe") and len(words) > 1 and words[1].lower() in ("/c", "/k"):
            words = words[2:]
        else:
            break
    return words


def _cd_target(words: list[str]) -> str | None:
    if not words or words[0].lower() not in _CD_NAMES:
        return None
    rest = [word for word in words[1:] if not word.startswith("-") and word.lower() != "/d"]
    return rest[0] if rest else None


def _build_args(words: list[str]) -> list[str] | None:
    """The arguments after ``build`` when this is ``flutter [global flags] build``, else None."""

    if not words or os.path.basename(words[0]).lower() not in _FLUTTER_NAMES:
        return None
    rest = words[1:]
    while rest and rest[0].startswith("-"):
        rest = rest[1:]
    if not rest or rest[0].lower() != "build":
        return None
    return rest[1:]


def _build_mode(args: list[str]) -> str:
    for mode in _MODES:
        if f"--{mode}" in args:
            return mode
    return "release"  # flutter build's default


def flutter_builds(command: str, base_dir: str | os.PathLike[str]) -> list[FlutterBuild]:
    """Every direct ``flutter build`` segment of ``command``, with the directory it runs in.

    A ``cd`` / ``Set-Location`` / ``pushd`` segment ahead of the build moves the
    directory the same way the shell would.
    """

    current = Path(os.path.expanduser(str(base_dir)))
    builds: list[FlutterBuild] = []
    for segment in _SEGMENT_SPLIT_RE.split(str(command or "")):
        words = _command_words(_tokens(segment))
        target_dir = _cd_target(words)
        if target_dir is not None:
            current = current / os.path.expanduser(target_dir)
            continue
        args = _build_args(words)
        if args is None:
            continue
        positional = [arg for arg in args if not arg.startswith("-")]
        builds.append(FlutterBuild(
            project_dir=current, target=(positional[0].lower() if positional else ""), mode=_build_mode(args),
        ))
    return builds


# ── FlutterCommand: one argv, classified (plan §4) ─────────────────────────────

COMMAND_BUILD = "build"
COMMAND_RUN = "run"
COMMAND_OTHER = "other"
#: ``dart run tool/stagec_parity_build.dart`` is the QA build: an isolated ``ParityStageC`` output.
QA_ISOLATED_TARGET = "qa_isolated"

_DART_NAMES = frozenset({"dart", "dart.exe", "dart.bat"})
_FLUTTER_TOOLS_SNAPSHOT = "flutter_tools.snapshot"
_QA_BUILD_SCRIPTS = ("tool/stagec_parity_build.dart",)
_DEVICE_FLAGS = frozenset({"-d", "--device-id"})


@dataclass(frozen=True)
class FlutterCommand:
    """What one Flutter/Dart argv runs: ``kind`` (build · run · other), target, mode, where, which toolchain."""

    kind: str
    target: str
    mode: str
    project_dir: Path
    toolchain: str


@dataclass(frozen=True)
class CommandRecognition:
    """The parser's answer: a :class:`FlutterCommand`, or the argv head it could not place.

    ``unrecognized_head`` is the evidence for a ``toolchain_unrecognized`` unknown; it is
    empty exactly when ``command`` is set.
    """

    command: FlutterCommand | None
    unrecognized_head: str = ""


def _mode(args: list[str], default: str) -> str:
    return next((mode for mode in _MODES if f"--{mode}" in args), default)


def _positional(args: list[str]) -> list[str]:
    return [arg for arg in args if not arg.startswith("-")]


def _build_command(args: list[str], cwd: Path, toolchain: str) -> FlutterCommand:
    positional = _positional(args)
    return FlutterCommand(COMMAND_BUILD, positional[0].lower() if positional else "", _build_mode(args), cwd, toolchain)


def _run_command(args: list[str], cwd: Path, toolchain: str) -> FlutterCommand:
    device = ""
    for index, arg in enumerate(args):
        if arg in _DEVICE_FLAGS and index + 1 < len(args):
            device = args[index + 1].lower()
        elif arg.startswith("--device-id="):
            device = arg.split("=", 1)[1].lower()
    target = f"{COMMAND_RUN}:{device}" if device else COMMAND_RUN
    return FlutterCommand(COMMAND_RUN, target, _mode(args, "debug"), cwd, toolchain)


#: ``flutter <sub>`` → the classifier for that subcommand; any other subcommand is ``other``.
_SUBCOMMANDS = {COMMAND_BUILD: _build_command, COMMAND_RUN: _run_command}


def _flutter_command(args: list[str], cwd: Path) -> FlutterCommand:
    rest = list(args)
    while rest and rest[0].startswith("-"):
        rest = rest[1:]
    classify = _SUBCOMMANDS.get(rest[0].lower()) if rest else None
    if classify is None:
        return FlutterCommand(COMMAND_OTHER, "", "", cwd, TOOLCHAIN_FLUTTER)
    return classify(rest[1:], cwd, TOOLCHAIN_FLUTTER)


def _dart_command(args: list[str], cwd: Path) -> FlutterCommand:
    lowered = [arg.replace("\\", "/").lower() for arg in args]
    snapshot = next((i for i, arg in enumerate(lowered) if arg.endswith(_FLUTTER_TOOLS_SNAPSHOT)), None)
    if snapshot is not None:
        # The Flutter tool itself, running in the Dart VM: what `flutter.bat` actually spawns.
        return _flutter_command(args[snapshot + 1:], cwd)
    if lowered[:1] == [COMMAND_RUN] and any(arg.endswith(_QA_BUILD_SCRIPTS) for arg in lowered[1:2]):
        return FlutterCommand(COMMAND_BUILD, QA_ISOLATED_TARGET, "release", cwd, TOOLCHAIN_DART)
    return FlutterCommand(COMMAND_OTHER, "", "", cwd, TOOLCHAIN_DART)


def recognize_argv(argv: list[str] | tuple[str, ...], cwd: str | os.PathLike[str]) -> CommandRecognition:
    """Classify one process argv (a detected process, a restart spec) run in ``cwd``."""

    words = _command_words([str(word) for word in argv])
    project = Path(os.path.expanduser(str(cwd)))
    head = os.path.basename(words[0]).lower() if words else ""
    if head in _FLUTTER_NAMES:
        return CommandRecognition(_flutter_command(words[1:], project))
    if head in _DART_NAMES:
        return CommandRecognition(_dart_command(words[1:], project))
    return CommandRecognition(None, unrecognized_head=head or "(empty argv)")


def recognize_command(command: str, base_dir: str | os.PathLike[str]) -> CommandRecognition:
    """Classify a SHELL line (a terminal tool command): the first build or run segment wins.

    A ``cd`` segment moves the directory exactly as :func:`flutter_builds` does. With no
    build or run segment, the answer is the last segment's classification.
    """

    current = Path(os.path.expanduser(str(base_dir)))
    answer = CommandRecognition(None, unrecognized_head="(empty command)")
    for segment in _SEGMENT_SPLIT_RE.split(str(command or "")):
        words = _command_words(_tokens(segment))
        target_dir = _cd_target(words)
        if target_dir is not None:
            current = current / os.path.expanduser(target_dir)
            continue
        if not words:
            continue
        answer = recognize_argv(words, current)
        if answer.command is not None and answer.command.kind != COMMAND_OTHER:
            return answer
    return answer
