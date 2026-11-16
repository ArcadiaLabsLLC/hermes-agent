"""Which tool on this host: the fork's ONE answer for git, node and the platform-default root
(FH-ONE-HOST-TOOL-RESOLVER, task one-tool-resolver-per-host).

Fork modules used to answer "which git" each their own way: a bare ``["git", ...]`` argv in a
dozen modules, a ``shutil.which("git")`` beside them, and the git door's own presence probe
(``realm_rekey_git.git_runs``) that raised on the phone wheel instead of answering. They ask here.

* **git** — :func:`git_command` is the argv[0] every fork git spawn uses (``git_cmd.run_git``
  included). On Windows it is PM's pinned Git for Windows when PM has installed it (the git whose
  ``bash.exe`` contract the tree trusts — the same order as upstream's
  ``hermes_cli.boot_bootstrap._git_binary``); everywhere else, and as the last fallback, it is the
  bare ``"git"``, so the child resolves it on the PATH the caller passes, exactly as before. PM's git
  package exists only on Windows ("POSIX uses system git by choice", ``pm/packages.py::Git``), so a
  POSIX host never reads PM's lockfile for it. :func:`git_resolution` reports the choice.
* :func:`git_runs` answers whether git can run here, and NEVER raises: on a profile whose wheel
  leaves the git door out (the phone: ``agent_runtime.git_cmd`` is a loud stand-in,
  ``loop_tool_lifecycles``) the answer is False — there is no git on a phone, so nothing cut a
  worktree or a brain there and a step that needs git has nothing to do.
* **node / npm / npx** — :func:`node_executable` is upstream's reviewed ``find_node_executable``
  (PM's selected Node, never the user's PATH copy).
* **the platform-default root** — :func:`platform_default_root` is the ``~/.hermes`` (or
  ``%LOCALAPPDATA%\\hermes``) a passed environment names, ``HERMES_DATA_DIR_SUFFIX`` included: the root
  the test seal points at its sandbox.

Lookup never installs, downloads, or starts anything (``hermes_platform/AGENTS.md``); PATH lookups go
through ``hermes_platform.resolver.locate_command``. ``tests/agent_runtime/test_host_tools_resolution.py``
refuses a bare tool lookup anywhere else in the fork's own modules (a shrink-only baseline).
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .module_presence import shipped

__layer__ = "models"
__all__ = [
    "GIT_DOOR",
    "ToolResolution",
    "git_command",
    "git_resolution",
    "git_runs",
    "node_executable",
    "platform_default_root",
]

#: The fork's git chokepoint; a wheel that omits it has no git (``loop_tool_lifecycles.GIT_COMMAND``).
GIT_DOOR = "agent_runtime.git_cmd"
_GIT = "git"
_PM = "pm"
_PATH = "PATH"
_MISSING = "missing"
_NOT_SHIPPED = "not_shipped"


@dataclass(frozen=True)
class ToolResolution:
    """Which ``command`` runs the tool and where it was found: ``pm``, ``PATH``, ``missing`` (the bare
    name, which the child will fail to find) or ``not_shipped`` (this wheel has no such tool)."""

    tool: str
    command: str
    source: str

    @property
    def found(self) -> bool:
        return self.source in (_PM, _PATH)


@functools.lru_cache(maxsize=8)
def _pm_git(hermes_home: str | None) -> str | None:
    """PM's installed git for this data root (keyed on ``HERMES_HOME``: a test's sandbox is its own)."""
    del hermes_home  # the cache key; PM reads the active root itself
    try:
        from pm import installed_package

        installed = installed_package(_GIT)
    except Exception:  # health: allow BLE001 -- a PM that cannot answer falls through to PATH
        return None
    return str(installed.binary) if installed is not None and installed.binary is not None else None


def _pm_git_here() -> str | None:
    if sys.platform != "win32":
        return None
    return _pm_git(os.environ.get("HERMES_HOME"))


def git_command() -> str:
    """argv[0] for a fork git spawn: PM's git on Windows when installed, else the bare ``"git"``."""
    return _pm_git_here() or _GIT


def git_resolution(path: str | None = None) -> ToolResolution:
    """Which git this host runs and where it was found; *path* is the PATH the child will get."""
    if not shipped(GIT_DOOR):
        return ToolResolution(_GIT, _GIT, _NOT_SHIPPED)
    pm_git = _pm_git_here()
    if pm_git:
        return ToolResolution(_GIT, pm_git, _PM)
    from hermes_platform.resolver import locate_command
    from hermes_platform.resolver.core import LookupContext

    found = locate_command(_GIT, LookupContext() if path is None else LookupContext(path=path))
    return ToolResolution(_GIT, found.command[0], _PATH) if found.command else ToolResolution(_GIT, _GIT, _MISSING)


def git_runs() -> bool:
    """Whether git runs on this host (``git --version`` exits 0). Never raises: a wheel without the git
    door (the phone) answers False, as does a host with no git."""
    if not shipped(GIT_DOOR):
        return False
    try:
        done = subprocess.run([git_command(), "--version"], capture_output=True, text=True, timeout=10,
                              stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def node_executable(command: str) -> str | None:
    """PM's selected node / npm / npx (upstream's reviewed ``find_node_executable``), or None."""
    from hermes_constants import find_node_executable

    return find_node_executable(command)


def platform_default_root(env: Mapping[str, str] | None = None) -> Path:
    """The platform-default Hermes root that *env* (default: this process's) names, suffix included.

    The rule is ``hermes_constants._get_platform_default_hermes_home``'s, over a passed mapping instead
    of ``os.environ`` (FH-RUNTIME-HOME-DEFAULT-DUPLICATE); a parity test pins the two together
    (``tests/agent_runtime/test_resolution_home_default_downstream.py``).
    """
    env = os.environ if env is None else env
    suffix = str(env.get("HERMES_DATA_DIR_SUFFIX") or "")
    if sys.platform == "win32":
        local_appdata = str(env.get("LOCALAPPDATA") or "").strip()
        base = Path(local_appdata).expanduser() if local_appdata else Path.home() / "AppData" / "Local"
        return base / ("hermes" + suffix)
    return Path.home() / (".hermes" + suffix)
