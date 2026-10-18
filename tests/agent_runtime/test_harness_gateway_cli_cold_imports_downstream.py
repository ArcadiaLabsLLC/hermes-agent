"""A gateway operator verb starts without the persona-chat and provider stacks.

Every ``hermes harness ...`` run is a cold interpreter. Until 2026-10-18
``hermes_cli.harness_support`` re-exported one string constant (read by nobody)
from ``agent_runtime.persona_chat_continuity``, whose package import walks
persona_assignments -> tool_visibility -> profile_readiness -> runtime_provider
-> models/auth: ~0.1 s per verb with bytecode written (1.56 s -> 1.45 s wall for
``gateway peers list`` in the test-child env, lane w8-slow-b) and ~1.9 s of
compile on a checkout without it. This runs a real verb in a sandboxed child
and reads what it loaded.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_PROBE = """
import sys
sys.argv = ["hermes", "harness", "gateway", "peers", "list", "--json"]
from hermes_cli.main import main
try:
    main()
except SystemExit:
    pass
heavy = [name for name in ("agent_runtime.persona_chat_continuity", "hermes_cli.runtime_provider")
         if name in sys.modules]
sys.stderr.write("LOADED=" + ",".join(heavy) + "\\n")
"""


# The child runs ``peers list``, a read of the sandboxed runtime root below
# (own HERMES_HOME, HOME, USERPROFILE, LOCALAPPDATA): it boots no serve and
# binds no port. Import cost is a property of a fresh interpreter only.
@pytest.mark.live_system_guard_bypass
def test_gateway_peers_list_loads_no_persona_chat_or_provider_stack(tmp_path):
    home = tmp_path / "home"
    for path in (home, tmp_path / "local", tmp_path / "runtime"):
        path.mkdir()
    env = dict(os.environ)
    env.update(
        HERMES_AGENT_RUNTIME_ROOT=str(tmp_path / "runtime"), HERMES_HOME=str(home),
        HERMES_HEAD_HOME=str(home), LOCALAPPDATA=str(tmp_path / "local"), HOME=str(home),
        USERPROFILE=str(home),
        PYTHONPATH=str(REPO_ROOT) + os.pathsep + (env.get("PYTHONPATH") or ""),
    )
    completed = subprocess.run([sys.executable, "-c", _PROBE], cwd=str(REPO_ROOT), env=env,
                               capture_output=True, text=True, timeout=120)
    assert '"items": []' in completed.stdout, completed.stdout + completed.stderr
    assert "LOADED=\n" in completed.stderr, completed.stderr
