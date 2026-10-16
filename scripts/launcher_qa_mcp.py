#!/usr/bin/env python3
"""Start the Eternia Launcher's QA MCP server (``launcher_qa``) for a session in this repo.

Everything machine-specific comes from the environment, so nothing personal is
committed and the same command works on every machine (owner ruling 2026-10-15):

  STAGEC_QA_REPO_ROOT    the EterniaLauncher checkout (required; ETERNIA_LAUNCHER_ROOT also read)
  STAGEC_LAUNCH_HELPER   the direct-EXE launch helper (default: the checkout's
                         docs/stages/qa-reboot/scripts/Start-StageCDirectExe.ps1)
  STAGEC_QA_TRANSPORT    default ``direct_control``

The server is the checkout's prebuilt ``tool/stagec_qa_mcp_server/build/stagec_qa_mcp_server[.exe]``
when present, else ``dart run tool/stagec_qa_mcp_server/bin/main.dart``. Register it once:

  claude mcp add launcher_qa -- python scripts/launcher_qa_mcp.py

``--print`` shows the resolved command and variables without starting anything.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HELPER = Path("docs/stages/qa-reboot/scripts/Start-StageCDirectExe.ps1")
SERVER_DIR = Path("tool/stagec_qa_mcp_server")


class LaunchRefused(Exception):
    """The environment does not name a usable launcher checkout."""


def resolve(env: dict[str, str]) -> tuple[list[str], Path, dict[str, str]]:
    """``(argv, cwd, env)`` for the server, from ``env`` alone."""

    raw = env.get("STAGEC_QA_REPO_ROOT") or env.get("ETERNIA_LAUNCHER_ROOT") or ""
    if not raw:
        raise LaunchRefused("set STAGEC_QA_REPO_ROOT (or ETERNIA_LAUNCHER_ROOT) to the EterniaLauncher checkout")
    root = Path(raw).expanduser()
    if not (root / SERVER_DIR / "bin" / "main.dart").is_file():
        raise LaunchRefused(f"{root} is not an EterniaLauncher checkout (no {SERVER_DIR}/bin/main.dart)")
    helper = Path(env.get("STAGEC_LAUNCH_HELPER") or root / HELPER).expanduser()
    if not helper.is_file():
        raise LaunchRefused(f"launch helper not found: {helper} (set STAGEC_LAUNCH_HELPER)")
    child = dict(env)
    child["STAGEC_QA_REPO_ROOT"] = str(root)
    child["STAGEC_LAUNCH_HELPER"] = str(helper)
    child.setdefault("STAGEC_QA_TRANSPORT", "direct_control")
    exe = root / SERVER_DIR / "build" / ("stagec_qa_mcp_server.exe" if os.name == "nt" else "stagec_qa_mcp_server")
    argv = [str(exe)] if exe.is_file() else ["dart", "run", (SERVER_DIR / "bin" / "main.dart").as_posix()]
    return argv, root, child


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        command, cwd, env = resolve(dict(os.environ))
    except LaunchRefused as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if "--print" in args:
        keys = ("STAGEC_QA_REPO_ROOT", "STAGEC_LAUNCH_HELPER", "STAGEC_QA_TRANSPORT")
        print(json.dumps({"argv": command, "cwd": str(cwd), "env": {k: env[k] for k in keys}}, indent=2))
        return 0
    return subprocess.run(command, cwd=cwd, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
