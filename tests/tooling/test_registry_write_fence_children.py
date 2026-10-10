"""A CHILD a test spawns cannot write the real Windows registry either.

The launcher's real-serve sandboxes (``p-l-longrun-*``) put ``<sandbox>\\home\\bin`` on
the operator's ``HKCU\\Environment\\Path`` from a ``python -m hermes_cli.main`` child,
where the pytest audit hook (``tests/_downstream/registry_write_fence.py``) cannot
reach. The plugin now exports ``HERMES_REGISTRY_WRITE_FENCE=1`` and ``hermes_bootstrap``
— the first import of every entry point — fences a child that inherits it.

Every write here goes to a throwaway key under ``HKCU\\Software``, never ``Environment``;
the control child deletes its own key, and the parent only reads.

A minimal tree that ships ``hermes_bootstrap`` without ``hermes_cli/_registry_write_fence.py``
must still start and still fence (the bootstrap's inline fallback): the ``absent`` case
blocks that one module in the child.

The PowerShell writer (``scripts/install.ps1::Set-LauncherUserPath``) honours the same inherited
marker: ``tests/scripts/test_install_ps1_path_fence_downstream.py`` (D3.15), not a second mechanism.

Mutation: replace the ``_fence_registry()`` call in ``hermes_bootstrap.py`` with ``pass``
-> every ``test_an_inherited_child_*`` case is red (the child prints WROTE).
Mutation: make the bootstrap's fallback ``_fence_registry`` a no-op -> the ``absent`` case
is red.
Mutation: drop the ``os.environ[CHILD_FENCE_ENV] = "1"`` line from
``registry_write_fence.install`` -> every case is red (the control asserts the marker).
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
# ``absent``: the module is blocked, as in a minimal tree that ships hermes_bootstrap without it.
_ABSENT = (
    "class _Absent:\n"
    "    def find_spec(self, name, path=None, target=None):\n"
    "        if name == 'hermes_cli._registry_write_fence':\n"
    "            raise ModuleNotFoundError(f'No module named {name!r}', name=name)\n"
    "sys.meta_path.insert(0, _Absent())\n"
)
_CHILD = (
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


def _run_child(path: str, *, isolated: bool, env: dict | None, absent: bool = False) -> str:
    code = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n" + (_ABSENT if absent else "") + _CHILD
    argv = [sys.executable, *(["-I"] if isolated else []), "-c", code, path]
    done = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.mark.parametrize(("isolated", "absent"), [(False, False), (True, False), (False, True)],
                         ids=["plain", "isolated", "module-absent"])
def test_an_inherited_child_registry_write_is_refused(isolated, absent):
    path = _throwaway_key()
    out = _run_child(path, isolated=isolated, env=None, absent=absent)  # env=None: inherits this test's

    assert out.startswith("REFUSED registry fence: winreg.CreateKey refused"), out
    assert ("hermes_bootstrap fallback" in out) is absent, out
    assert not _key_exists(path)


@pytest.mark.parametrize("absent", [False, True], ids=["module", "module-absent"])
def test_the_same_child_writes_when_the_fence_is_off(absent):
    # Positive control: identical child bytes, the one variable is the inherited marker.
    assert os.environ.get(CHILD_FENCE_ENV) == "1"
    path = _throwaway_key()
    env = {name: value for name, value in os.environ.items() if name != CHILD_FENCE_ENV}

    out = _run_child(path, isolated=False, env=env, absent=absent)

    assert out.strip() == "WROTE", out
    assert not _key_exists(path)  # the child removed its own throwaway key
