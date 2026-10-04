"""Refuse an agent ``flutter build`` that would collide with the operator's live Launcher.

The RW4 guidance (``harness-runtime-model`` SKILL.md, "A screenshot request is a
``launcher_qa`` call, never a build") was installed and an agent still ran
``flutter build windows --debug`` in the operator's primary Launcher checkout while
that Launcher ran from its Debug output — the WebView2Loader.dll lock failure class
(runtime-queue row, events archive 2026-10-01). This is the hard half of that rule,
reached through the eternia-harness ``pre_tool_call`` hook.

A ``terminal`` call is refused when one of its command segments is a direct
``flutter build`` (``flutter``, ``flutter.bat``, ``flutter.exe``, ``fvm flutter``)
and either

* its project directory sits in the operator's PRIMARY Launcher checkout — the
  checkout bound to the ``eternia_launcher`` machine root
  (``agent_runtime.machine_roots``; never a hardcoded path; an unbound root leaves
  only the second test), or
* the build's mode output directory (``build/windows/<arch>/runner/<Mode>``,
  ``build/linux/<arch>/<mode>/bundle``, ``build/macos/Build/Products/<Mode>``) holds
  the executable of a running process.

A build reached through ``dart run`` or a script (``tool/stagec_parity_build.dart``,
which writes its own ``ParityStageC`` output) is out of scope by design.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__layer__ = "policy"

logger = logging.getLogger(__name__)

LAUNCHER_ROOT_NAME = "eternia_launcher"

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


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def _checkout_root(path: Path) -> Path:
    """The nearest directory at or above ``path`` holding ``.git`` (a worktree's ``.git`` file counts)."""

    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return path


def primary_launcher_root() -> Path | None:
    """The operator's primary Launcher checkout, from the machine-root registry."""

    try:
        from agent_runtime.machine_roots import load_machine_roots

        return load_machine_roots().get(LAUNCHER_ROOT_NAME)
    except Exception:
        logger.debug("machine roots unavailable for the flutter build guard", exc_info=True)
        return None


def is_primary_checkout(project_dir: Path, primary: Path | None) -> bool:
    if primary is None:
        return False
    return _norm(_checkout_root(project_dir)) == _norm(primary)


def build_output_dirs(build: FlutterBuild) -> list[Path]:
    """The directories this build overwrites that a running Launcher executes from."""

    layout = _OUTPUT_LAYOUTS.get(build.target)
    return [] if layout is None else layout(build.project_dir / "build", build.mode)


#: Per target: ``(build root, mode) -> the directories a running Launcher executes from``.
_OUTPUT_LAYOUTS = {
    "windows": lambda root, mode: [arch / "runner" / mode.capitalize() for arch in _children(root / "windows")],
    "linux": lambda root, mode: [arch / mode / "bundle" for arch in _children(root / "linux")],
    "macos": lambda root, mode: [root / "macos" / "Build" / "Products" / mode.capitalize()],
}


def _children(path: Path) -> list[Path]:
    try:
        return [child for child in path.iterdir() if child.is_dir()]
    except OSError:
        return []


def running_executable_in(directories: list[Path]) -> tuple[int, str] | None:
    """``(pid, exe)`` of a running process whose executable lives under one of ``directories``."""

    prefixes = [_norm(directory) + os.sep for directory in directories if directory.is_dir()]
    if not prefixes:
        return None
    import psutil

    for process in psutil.process_iter(["pid", "exe"]):
        exe = process.info.get("exe")
        if exe and any(_norm(Path(exe)).startswith(prefix) for prefix in prefixes):
            return process.info["pid"], exe
    return None


def _terminal_base_dir(args: dict[str, Any], task_id: str) -> str:
    """The directory the terminal tool would run in: workdir, task override, session cwd, config cwd."""

    workdir = args.get("workdir")
    if isinstance(workdir, str) and workdir.strip():
        return workdir
    try:
        from tools.terminal_tool import get_session_cwd, resolve_task_overrides

        recorded = resolve_task_overrides(task_id).get("cwd") or get_session_cwd(task_id)
        if recorded:
            return str(recorded)
    except Exception:
        logger.debug("terminal cwd unavailable for the flutter build guard", exc_info=True)
    return os.environ.get("TERMINAL_CWD", "").strip() or os.getcwd()


def _refusal(reason: str) -> str:
    return (
        f"BLOCKED by the Eternia harness: `flutter build` refused — {reason}. A running Launcher "
        "locks its build output (the .exe, WebView2Loader.dll), so this build fails after minutes or "
        "breaks the operator's session. For QA or a screenshot call `mcp_launcher_qa_launch_or_attach` "
        "(for a tab screenshot, `mcp_launcher_qa_open_app_tab` with `screenshot: true`) and REPORT any typed blocker it returns instead of "
        "building. If a QA binary really must be built, run the Launcher's `tool/stagec_parity_build.dart` "
        "(isolated `ParityStageC` output; attach with `exe_dir`), or build in a separate git worktree — "
        "never in the operator's primary checkout or into a runner directory a process is executing from."
    )


def flutter_build_refusal(tool_name: Any, args: Any, task_id: str = "") -> str | None:
    """The refusal for a terminal call whose ``flutter build`` collides with a live Launcher, else None."""

    if tool_name != "terminal" or not isinstance(args, dict):
        return None
    command = args.get("command")
    if not isinstance(command, str) or "flutter" not in command.lower():
        return None
    builds = flutter_builds(command, _terminal_base_dir(args, task_id))
    if not builds:
        return None
    primary = primary_launcher_root()
    for build in builds:
        if is_primary_checkout(build.project_dir, primary):
            return _refusal(
                f"its project directory {build.project_dir} is the operator's primary Launcher checkout "
                f"(machine root `{LAUNCHER_ROOT_NAME}`)"
            )
        held = running_executable_in(build_output_dirs(build))
        if held is not None:
            pid, exe = held
            return _refusal(f"its output directory holds {exe}, which running process {pid} is executing")
    return None
