"""A CHILD a test spawns cannot write the real Windows registry either.

The launcher's real-serve sandboxes (``p-l-longrun-*``) put ``<sandbox>\\home\\bin`` on
the operator's ``HKCU\\Environment\\Path`` from a ``python -m hermes_cli.main`` child,
where the pytest audit hook (``tests/_downstream/registry_write_fence.py``) cannot
reach. The plugin now exports ``HERMES_REGISTRY_WRITE_FENCE=1`` and ``hermes_bootstrap``
— the first import of every entry point — fences a child that inherits it.

Every write here goes to a throwaway key under ``HKCU\\Software``, never ``Environment``;
the control child deletes its own key, and the parent only reads.

Mutation: delete ``install_if_requested()`` from ``hermes_bootstrap.py`` -> both
``test_an_inherited_child_*`` cases are red (the child prints WROTE).
Mutation: drop the ``os.environ[CHILD_FENCE_ENV] = "1"`` line from
``registry_write_fence.install`` -> all three are red (the control asserts the marker).
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests._downstream.registry_write_fence import CHILD_FENCE_ENV

pytestmark = pytest.mark.platforms("windows")

ROOT = Path(__file__).resolve().parents[2]

# The child boots the way an entry point does (``import hermes_bootstrap`` first), then
# tries to create and write a throwaway key, cleaning up after itself if it got one.
_CHILD = (
    "import sys\n"
    f"sys.path.insert(0, {str(ROOT)!r})\n"
    "import hermes_bootstrap\n"
    "import winreg\n"
    "path = sys.argv[1]\n"
    "try:\n"
    "    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)\n"
    "except PermissionError as exc:\n"
    "    print('REFUSED', exc)\n"
    "    raise SystemExit(0)\n"
    "try:\n"
    "    winreg.SetValueEx(key, 'probe', 0, winreg.REG_SZ, 'x')\n"
    "    print('WROTE')\n"
    "finally:\n"
    "    winreg.CloseKey(key)\n"
    "    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)\n"
)


def _throwaway_key() -> str:
    return f"Software\\HermesRegistryFenceProbe-{uuid.uuid4().hex}"


def _key_exists(path: str) -> bool:
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, path))
    except FileNotFoundError:
        return False
    return True


def _run_child(path: str, *, isolated: bool, env: dict | None) -> str:
    argv = [sys.executable, *(["-I"] if isolated else []), "-c", _CHILD, path]
    done = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.mark.parametrize("isolated", [False, True], ids=["plain", "isolated"])
def test_an_inherited_child_registry_write_is_refused(isolated):
    path = _throwaway_key()
    out = _run_child(path, isolated=isolated, env=None)  # env=None: the child inherits this test's

    assert out.startswith("REFUSED registry fence: winreg.CreateKey refused"), out
    assert not _key_exists(path)


def test_the_same_child_writes_when_the_fence_is_off():
    # Positive control: identical child bytes, the one variable is the inherited marker.
    assert os.environ.get(CHILD_FENCE_ENV) == "1"
    path = _throwaway_key()
    env = {name: value for name, value in os.environ.items() if name != CHILD_FENCE_ENV}

    out = _run_child(path, isolated=False, env=env)

    assert out.strip() == "WROTE", out
    assert not _key_exists(path)  # the child removed its own throwaway key
