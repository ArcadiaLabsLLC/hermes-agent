"""The session's Hermes home is never the operator's, however pytest is launched.

``scripts/run_tests.sh`` execs ``env -i`` without ``HERMES_HOME``, so
``tests/conftest.py`` mints a throwaway session home and every process the
suite spawns inherits it. Bare ``python -m pytest <file>`` from an operator
shell did not: ``tests/conftest.py`` honours a pre-set ``HERMES_HOME`` that is
not the platform default (``X:/Eternia/.hermes`` is "custom" by that test), so
the session environment kept the LIVE home. Each test's ``_isolate_env`` moved
it to ``tmp_path`` for the test's own body, but a child spawned outside that
window — a session/module fixture, a worker still running after teardown
restored the env — inherited the live home and logged into its ``agent.log``
(lane h-suite-speed, 2026-10-05: 142 lines).

The root ``conftest.py`` calls :func:`detach_operator_home` at import, before
``tests/conftest.py`` runs, so a bare run arrives in the same state as the
runner's: no home-shaped variable, the real root recorded under the test-only
``HERMES_TEST_REAL_ROOT`` (the name the runner already forwards to the gateway
fence). :func:`live_home_refusal` is the session-start backstop.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable, MutableMapping

#: Variables that name a live store; a child reading any of them would act on it.
DETACHED_VARS = ("HERMES_HOME", "HERMES_HEAD_HOME", "HERMES_AGENT_RUNTIME_ROOT")
#: Test-only name for the operator's real root (``scripts/run_tests.sh`` sets it too).
REAL_ROOT_ENV = "HERMES_TEST_REAL_ROOT"
#: Exported by ``tests/conftest.py``; present means this process was spawned BY a test.
ISOLATION_ENV = "HERMES_TEST_ISOLATION"
SANDBOX_ENV = "HERMES_TEST_SANDBOX_HOME"
#: A file only a used install has; a freshly minted session home never does.
LIVE_INSTALL_MARKERS = ("state.db",)


def detach_operator_home(environ: MutableMapping[str, str]) -> str | None:
    """Strip the operator's home-shaped variables; return the real root recorded.

    A process spawned by a test (``HERMES_TEST_ISOLATION`` inherited) already
    carries a test home and is left alone.
    """
    if environ.get(ISOLATION_ENV):
        return None
    home = (environ.get("HERMES_HOME") or "").strip()
    if home and not environ.get(REAL_ROOT_ENV, "").strip():
        from hermes_constants import get_default_hermes_root

        environ[REAL_ROOT_ENV] = str(get_default_hermes_root(home=home))
    for name in DETACHED_VARS:
        environ.pop(name, None)
    return environ.get(REAL_ROOT_ENV) or None


def ensure_session_home(environ: MutableMapping[str, str]) -> str:
    """The session home; minted here only for a tree whose conftest did not mint one."""
    home = (environ.get("HERMES_HOME") or "").strip()
    if not home:
        home = tempfile.mkdtemp(prefix="hermes-test-home-")
        environ["HERMES_HOME"] = home
        environ.setdefault(SANDBOX_ENV, home)
    return home


def real_roots(environ: MutableMapping[str, str]) -> list[Path]:
    """Every root the session home must stay out of: the recorded one and the defaults."""
    candidates: list[str | Path] = [environ.get(REAL_ROOT_ENV, "").strip()]
    local_app_data = environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:  # the native-Windows install root
        candidates.append(Path(local_app_data) / "hermes")
    candidates.append(Path(os.path.expanduser("~")) / ".hermes")
    roots: list[Path] = []
    for candidate in candidates:
        if not candidate:
            continue
        resolved = Path(candidate).expanduser().resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def live_home_refusal(
    home: str | os.PathLike[str], roots: Iterable[Path], *, check_markers: bool = True
) -> str | None:
    """Why *home* may not serve as the session home, or ``None`` when it may.

    *check_markers* is off for a pytest spawned BY a test, whose home is the
    parent test's own fixture and may legitimately hold a planted ``state.db``.
    """
    resolved = Path(home).expanduser().resolve()
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            return f"the session HERMES_HOME {resolved} is inside the real install root {root}"
    for marker in LIVE_INSTALL_MARKERS if check_markers else ():
        if (resolved / marker).exists():
            return f"the session HERMES_HOME {resolved} already holds {marker}: a used install, not a fresh sandbox"
    return None
