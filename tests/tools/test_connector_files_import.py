"""``tools.connectors.gateway.files`` imports without pydantic.

``tool_search`` reaches ``files`` through ``connectors.search`` -> ``gateway.bridge`` on every
turn, connectors enabled or not, so ``files`` reads ``gateway.wire`` (pydantic models) only when
a file input is actually staged or refused.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_IMPORT_WITHOUT_PYDANTIC = """
import sys
sys.modules["pydantic"] = None  # any `import pydantic` now raises ImportError
import tools.connectors.gateway.files  # noqa: F401
print("wire loaded:", "tools.connectors.gateway.wire" in sys.modules)
"""


def test_files_imports_without_pydantic():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _IMPORT_WITHOUT_PYDANTIC],
        capture_output=True,
        check=False,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert "wire loaded: False" in proc.stdout
