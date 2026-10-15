"""The charsheet packaging boundary (program ruling Q9).

``agent/charsheet/`` ships in the plain hermes wheel and ``agent_runtime`` does
not, so no module of the package may import ``agent_runtime`` at import time.
Its one reach — where the install-wide character library lives — is a CALL-time
import in ``agent.charsheet._support.shared_characters_dir``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_PROBE = textwrap.dedent(
    """
    import sys

    class _NoRuntime:
        def find_spec(self, name, path=None, target=None):
            if name == "agent_runtime" or name.startswith("agent_runtime."):
                raise ImportError(f"{name} is not in the shipped wheel")
            return None

    sys.meta_path.insert(0, _NoRuntime())
    import agent.charsheet.draft
    import agent.charsheet.pipeline
    from agent.charsheet.draft import CharacterDraft, sprite_payload
    print("IMPORTED")
    try:
        agent.charsheet.draft.characters_dir()
    except ImportError as exc:
        print("CALL-REFUSED", exc)
    """
)


def _run_without_runtime() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_the_package_imports_without_agent_runtime():
    result = _run_without_runtime()

    assert "IMPORTED" in result.stdout, result.stderr


def test_only_the_library_location_needs_the_runtime_and_only_at_call_time():
    """Positive control for the test above: the probe really does block
    ``agent_runtime`` — the one call that needs it is refused."""
    result = _run_without_runtime()

    assert "CALL-REFUSED agent_runtime" in result.stdout, result.stderr
