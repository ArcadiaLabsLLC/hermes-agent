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
