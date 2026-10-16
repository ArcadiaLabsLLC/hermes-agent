"""Fork-owned: extend the environment the runtime already runs from by one extra, in place.

Owner ruling 2026-10-15 (wave w1015b-con-x): a provider's missing SDK extra is installed INTO
the existing environment; only a resolver conflict sends the caller to a new generation
(``pm.client.sync_venv``). A Windows sharing violation (``os error 32``: a file the serve or a
scanner holds) is re-run on the sync's own schedule before it raises. Lives inside ``pm``
because the uv invocation is private to it; upstream's own module is not edited.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

__all__ = ["extend_environment"]


def extend_environment(requirements: Sequence[str], *, environment: Path, explicit: bool = False,
                       timeout: int = 300) -> bool:
    """Install ``requirements`` into ``environment`` in place. False on a resolver conflict."""
    from pm.environment import (
        ResolutionConflict, _retry_sync_on_sharing_violation, classify_uv_failure, managed_environment,
    )
    from pm.environments import venv_python
    from pm.operations import _require_install_allowed, _requirements

    _require_install_allowed(explicit)
    requirements = _requirements(requirements)
    environment = Path(environment).absolute()
    python = venv_python(environment)
    engine = managed_environment(environment, python=python, explicit=explicit)
    command = ["pip", "install", "--python", str(python), *requirements]
    result = engine._run(command, cwd=environment, timeout=timeout)
    result = _retry_sync_on_sharing_violation(engine._run, command, environment, timeout, result)
    if not result.returncode:
        return True
    failure = classify_uv_failure("pip install", result.returncode, result.stderr or result.stdout)
    if isinstance(failure, ResolutionConflict):
        return False
    raise failure
