"""The config schema loads without ``tools.wake_word`` (its import is lazy)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_config_schema_loads_without_wake_word():
    """An install that does not package ``tools.wake_word`` still loads the config schema."""

    def providers(block_wake_word: bool) -> list:
        code = ("import json, sys\n"
                + ("sys.modules['tools.wake_word'] = None\n" if block_wake_word else "")
                + "import hermes_cli.web_server_config as m\n"
                  "print(json.dumps(m.CONFIG_SCHEMA['wake_word.provider']['options']))\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=120, check=True)
        return json.loads(done.stdout.strip().splitlines()[-1])

    assert len(providers(block_wake_word=False)) > 1  # positive control: the engines are offered
    assert providers(block_wake_word=True) == ["auto"]
