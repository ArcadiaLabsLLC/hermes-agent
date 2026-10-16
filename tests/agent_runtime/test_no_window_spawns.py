"""Test-spawned serves never draw a console window on the operator's screen (owner 2026-10-15).

Every ``subprocess.Popen`` / ``subprocess.run`` in the serve fixtures and the child e2e
files passes ``creationflags`` (``tests/agent_runtime/_no_window.no_window``). The AST walk
over CALLS is a gate on what is never written (a spawn with no flags), so a source walk is
the right instrument; ``test_serve_ended_sidecar_child_e2e.py`` sets its own console flags on
purpose (it tests console-signal delivery) and still must name them.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from tests.agent_runtime._no_window import NO_WINDOW, no_window

HERE = Path(__file__).resolve().parent
SPAWNING = sorted([HERE / "_serve_fixtures.py", *HERE.glob("test_*_child_e2e.py"), *HERE.glob("test_gateway_peer_*_e2e.py")])


def spawns_without_flags(paths) -> list[str]:
    found = []
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("Popen", "run") and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                    and not any(k.arg in ("creationflags", None) for k in node.keywords)):
                found.append(f"{path.name}:{node.lineno}")
    return found


def test_every_test_child_spawn_names_its_creationflags():
    assert len(SPAWNING) >= 5
    assert not spawns_without_flags(SPAWNING), "pass creationflags=no_window(...) — a test never draws a window"


def test_the_walk_sees_a_bare_spawn(tmp_path):
    planted = tmp_path / "x.py"
    planted.write_text("import subprocess\nsubprocess.Popen(['a'])\nsubprocess.run(['a'], creationflags=0)\n", encoding="utf-8")
    assert spawns_without_flags([planted]) == ["x.py:2"]


def test_no_window_keeps_the_callers_flags_and_never_joins_detached():
    group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    assert no_window(group) == group | NO_WINDOW
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    if detached:
        assert no_window(detached) == detached
