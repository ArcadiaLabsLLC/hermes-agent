"""RT-WIN-CONSOLE-FLASH-CODEX-SWITCH: every codex CLI spawn hides its console on Windows.

A serve the launcher starts detached has no console, so a console child it spawns without
``CREATE_NO_WINDOW`` opens a fresh window. ``check_codex_binary`` (``codex --version``) spawned
without the flag while the ``codex app-server`` Popen beside it hid. Fork-owned test of a fork
line in the upstream ``agent/transports/codex_app_server.py``.
"""

import ast
import subprocess
from pathlib import Path

from agent.transports import codex_app_server
from hermes_cli import _subprocess_compat

_HIDE = 0x08000000  # CREATE_NO_WINDOW
_MODULE = Path(codex_app_server.__file__)


def test_the_version_probe_spawns_with_the_hide_flags(monkeypatch):
    seen: dict = {}

    def _run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="codex-cli 99.0.0\n", stderr="")

    monkeypatch.setattr(_subprocess_compat, "windows_hide_flags", lambda: _HIDE)
    monkeypatch.setattr(codex_app_server.subprocess, "run", _run)
    ok, _ = codex_app_server.check_codex_binary(codex_bin="codex")
    assert ok
    assert seen.get("creationflags") == _HIDE


def test_every_subprocess_spawn_in_the_codex_transport_passes_creationflags():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    spawns = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) in {"subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.call"}
    ]
    assert len(spawns) >= 2, "the walk found fewer spawns than the module has"
    bare = [ast.unparse(node.func) + f"@{node.lineno}" for node in spawns
            if not any(kw.arg == "creationflags" for kw in node.keywords)]
    assert bare == []
