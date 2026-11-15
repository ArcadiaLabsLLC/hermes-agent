"""Fork-owned: a launch under a borrowed home with no install state of its own (ledger row ``pm/environments.py``).

Row RT-WORKTREE-LAUNCHER-UNDER-A-BORROWED-HOME-RUNS-WITHOUT-ITS-PACKAGES (owner 2026-11-15: "Yes, edit
upstream"). A checkout's ``.hermes/bin/hermes`` execs its OWNER's store Python. Run under another
``HERMES_HOME`` that holds no state for the checkout (a worktree's hermes under an Eternia QA copy's
home), upstream's ``activate_dependencies`` found nothing to select, and ``_require_own_dependencies``
compared the interpreter with the BORROWER's ``tools/`` store -- so the store Python ran bare, with no
dependency ``site-packages`` (``ruamel``/``psutil`` imports failed or degraded).

Here, before upstream's refusal runs:

* the root ``owning_home_root`` names holds a committed environment -> run on it, read-only: the
  generation is leased so the owner's collector keeps it, nothing is synced or written there;
* no owner, and this interpreter is a bare PM store Python (whichever root's store the launcher execs)
  -> refuse exactly as the unset-home launch does (``NoCommittedEnvironment``).

Anything else returns ``None`` and upstream's own branch decides. Stdlib only, as ``pm.environments``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _owner_committed_venv(owner: Path, project_root: Path) -> Path | None:
    from pm.environments import install_key

    state = owner / "installs" / install_key(project_root)
    try:
        data = json.loads((state / "facts.json").read_text(encoding="utf-8-sig"))
        value = data.get("packages", {}).get("venv", {}).get("environment")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(value, str):
        return None
    environment = Path(value).resolve()
    if not environment.is_relative_to((state / "environments").resolve()) or not (environment / "pyvenv.cfg").is_file():
        return None
    return environment


def _bare_store_python() -> bool:
    """Is this process a bare interpreter from a PM tool store (any root's ``tools/``)?

    A store is recognised by its own record, ``<store>/facts.json`` with a ``python`` package --
    PM's data format, read the way ``_require_own_dependencies`` reads ``store_root``, but for
    whichever root's store the launcher execs (an older interpreter left beside a newer entry
    included), since a borrowed home's ``store_root`` names the borrower's.
    """
    if sys.prefix != sys.base_prefix:
        return False  # a venv interpreter carries its own packages
    try:
        store = Path(sys.base_prefix).resolve().parent
        facts = json.loads((store / "facts.json").read_text(encoding="utf-8-sig"))
        return isinstance(facts.get("packages", {}).get("python"), dict)
    except (OSError, ValueError, AttributeError, RuntimeError):
        return False


def borrowed_home_environment(project_root: Path) -> Path | None:
    """The owner's committed environment for a borrowing launch with no state; refuses a bare store Python."""
    from pm import environments

    root = Path(project_root).resolve()
    owner = environments.owning_home_root(root)
    if owner is not None:
        environment = _owner_committed_venv(owner, root)
        if environment is not None:
            from hermes_cli.runtime_state import lease_generation

            # Held until exit so the owner's collector keeps it; re-read after leasing, as upstream's
            # unlocked path does, in case the owner committed a newer generation in between.
            try:
                release = lease_generation(environment)
                while (current := _owner_committed_venv(owner, root)) not in (None, environment):
                    release()
                    environment, release = current, lease_generation(current)
            except OSError:
                pass  # an owner's tree this user cannot lease in: run on it unleased
            return environment
    if _bare_store_python():
        raise environments.NoCommittedEnvironment("no dependency environment is committed for this install")
    return None
