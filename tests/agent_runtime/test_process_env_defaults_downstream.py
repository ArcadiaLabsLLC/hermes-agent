"""Process-env defaults are applied by process composers, never by plugin code (v0216 plan §2).

Gate for the class "a process default written at plugin-load time": the third instance was
upstream's ``profiles.describe`` red at v0.21.6 (its lazy discovery ran the harness plugin's
``register()``, which wrote ``HERMES_KANBAN_CLAIM_TTL_SECONDS``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime.process_env_defaults import HARNESS_PROCESS_ENV_DEFAULTS

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_serve_composer_carries_the_defaults_its_conversation_engine_reads(monkeypatch):
    """Conversations run in the serve's own process now (the worker process is retired),
    so the serve's composer is the one that must write the defaults."""
    import types

    from hermes_cli.harness_parts.serve import commands

    for key in HARNESS_PROCESS_ENV_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    # A non-ndjson transport is refused right after the composer step, before any boot.
    assert commands._cmd_serve(types.SimpleNamespace(ndjson=False)) != 0
    for key, value in HARNESS_PROCESS_ENV_DEFAULTS.items():
        assert os.environ.get(key) == value, key


@pytest.mark.timeout(180)
def test_plugin_discovery_writes_no_process_env(tmp_path):
    """Positive at runtime: a real interpreter, hermetic home, discovery between two snapshots."""
    home = tmp_path / ".hermes"
    home.mkdir()
    code = (
        "import os, json\n"
        "before = dict(os.environ)\n"
        "from hermes_cli.plugins import discover_plugins\n"
        "discover_plugins()\n"
        "after = dict(os.environ)\n"
        "print(json.dumps(sorted(k for k in after if before.get(k) != after[k])))\n"
    )
    env = {**os.environ, "HERMES_HOME": str(home), "PYTHONPATH": str(REPO_ROOT)}
    for key in HARNESS_PROCESS_ENV_DEFAULTS:
        env.pop(key, None)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=160, cwd=REPO_ROOT, env=env, check=False)
    assert out.returncode == 0, out.stderr[-2000:]
    changed = out.stdout.strip().splitlines()[-1]
    assert not set(HARNESS_PROCESS_ENV_DEFAULTS) & set(__import__("json").loads(changed)), changed
