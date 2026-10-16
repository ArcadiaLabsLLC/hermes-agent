"""Run-serialization S4: a grounded run's directory is context-local — no ``os.chdir``.

Plan: ``docs/agent-runtime-harness/planned/run-serialization-retirement-2026-10-15.md`` S4.

Two runs grounded in two different workdirs, inside ``_agent_workdir`` at the same
moment on two threads. Each must see its OWN directory through every upstream cwd
channel a tool reads — the terminal tool's ``TERMINAL_CWD`` (``_tenv``),
``resolve_agent_cwd()`` (system prompt, context files), and the file tools' relative-path
anchor — and a relative write must land in its own tree. The process cwd never moves.

Kill-mutation: in ``_agent_workdir`` replace ``set_terminal_scope({...})`` with a plain
``os.environ["TERMINAL_CWD"] = str(path)``. The two runs then share one process-global
value; the second writer wins and one run's relative write lands in the other's tree.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from agent_runtime.profile_runner.workdir import _agent_workdir


def test_two_grounded_runs_each_resolve_and_write_in_their_own_workdir(tmp_path, monkeypatch):
    from agent.runtime_cwd import resolve_agent_cwd
    from tools.file_tools_paths import _resolve_path_for_task
    from tools.terminal_tool_config import _tenv

    monkeypatch.setenv("TERMINAL_ENV", "local")
    process_cwd = os.getcwd()
    both_inside = threading.Barrier(2, timeout=30)
    seen: dict[str, dict[str, str]] = {}
    errors: list[BaseException] = []

    def run(name: str) -> None:
        try:
            workdir = tmp_path / f"repo-{name}"
            workdir.mkdir()
            with _agent_workdir(workdir):
                both_inside.wait()  # the other run is grounded too, right now
                target = Path(_resolve_path_for_task("note.txt", task_id=f"runser-s4-{name}"))
                target.write_text(name, encoding="utf-8")
                view = {
                    "terminal_cwd": _tenv("TERMINAL_CWD"),
                    "agent_cwd": str(resolve_agent_cwd()),
                    "written": str(target),
                    "process_cwd": os.getcwd(),
                }
                both_inside.wait()
            seen[name] = view
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(n,)) for n in ("alpha", "beta")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors, errors
    for name in ("alpha", "beta"):
        workdir = (tmp_path / f"repo-{name}").resolve()
        view = seen[name]
        assert Path(view["terminal_cwd"]) == workdir, view
        assert Path(view["agent_cwd"]).resolve() == workdir, view
        assert Path(view["written"]).resolve() == workdir / "note.txt", view
        assert (workdir / "note.txt").read_text(encoding="utf-8") == name
        assert view["process_cwd"] == process_cwd, view
    assert os.getcwd() == process_cwd


def test_no_workdir_binds_nothing(monkeypatch):
    """Positive control for the ungrounded arm: no workdir, no scope, the env answers."""

    from tools.terminal_scope import get_terminal_scope
    from tools.terminal_tool_config import _tenv

    monkeypatch.setenv("TERMINAL_CWD", "sentinel-cwd")
    with _agent_workdir(None):
        assert get_terminal_scope() is None
        assert _tenv("TERMINAL_CWD") == "sentinel-cwd"
