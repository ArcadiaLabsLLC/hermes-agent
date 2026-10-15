"""Fork seam: never activate a dependency generation built for another Python.

``pm.environments.activate_dependencies`` puts the committed generation's ``site-packages``
on ``sys.path`` without asking which interpreter the generation was built for. When the
process booting it is a different minor version -- the base CPython 3.12 behind the old
``venvs/hermes-agent`` launcher, with PM's generation built on its 3.14 store Python --
every pure-Python package imports and every compiled one does not (``pydantic_core``'s
``cp314`` extension is invisible to 3.12). The gateway then runs for hours with ``openai``
unimportable and every cron job failing (2026-09-29, profile alice).

``venv_sync.prepare_launch`` already re-enters the managed interpreter for a self-updating
install, but it answers ``None`` on several paths (a developer checkout, a process spawned
under a live update, a degraded completion) and activation proceeds on the booting
interpreter. This is the second gate, asked of the generation itself: when its interpreter
differs from ours, relaunch into the generation's own interpreter.
"""

from __future__ import annotations

import sys
from pathlib import Path


def generation_python_version(venv: Path) -> tuple[int, int] | None:
    """The (major, minor) a venv was built for, from ``pyvenv.cfg``.

    ``pm.environments.venv_python_version`` reads only the stdlib ``venv`` key ``version``;
    uv writes ``version_info`` instead and PM builds its generations with uv, so on Windows
    (where there is no ``lib/python3.x`` directory to fall back on) that reader answers
    ``None`` for every real generation. Both keys are read here, ``version_info`` first.
    """
    try:
        text = (venv / "pyvenv.cfg").read_text(encoding="utf-8-sig")
    except OSError:
        text = ""
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    for key in ("version_info", "version"):
        major, _, rest = values.get(key, "").partition(".")
        minor, _, _ = rest.partition(".")
        if major.isdigit() and minor.isdigit():
            return int(major), int(minor)
    from pm.environments import venv_python_version

    return venv_python_version(venv)


def generation_interpreter_for_mismatch(project_root: Path) -> Path | None:
    """The committed generation's interpreter when it is not this interpreter's version, else ``None``.

    ``None`` also when nothing is committed or the generation's version cannot be read: that
    is activation's own decision, and this gate only refuses what it can prove is wrong.
    Raises ``RuntimeError`` when the generation is foreign and has no interpreter to re-enter.
    """
    from pm.environments import committed_venv, venv_python

    environment = committed_venv(project_root)
    if environment is None:
        return None
    built_for = generation_python_version(environment)
    running = (sys.version_info.major, sys.version_info.minor)
    if built_for is None or built_for == running:
        return None
    python = venv_python(environment)
    if not python.is_file():
        raise RuntimeError(
            f"the dependency environment {environment} is built for Python "
            f"{built_for[0]}.{built_for[1]}, this interpreter is {running[0]}.{running[1]} "
            f"({sys.executable}), and the environment has no interpreter to relaunch into")
    return python


def refuse_foreign_generation(project_root: Path) -> None:
    """Raise ``RuntimeError`` when the committed generation was built for another Python.

    For an entry point that cannot re-enter itself -- the cron external worker, whose pid and
    ownership acknowledgement its spawner already holds -- refusing before activation is the
    honest answer: the spawner reports the pre-ack exit with this message.
    """
    python = generation_interpreter_for_mismatch(project_root)
    if python is not None:
        raise RuntimeError(
            f"the dependency environment {python.parent.parent} is built for Python "
            f"{'.'.join(map(str, generation_python_version(python.parent.parent) or ()))}, "
            f"this interpreter is {sys.version_info.major}.{sys.version_info.minor} "
            f"({sys.executable}); start it with {python}")
