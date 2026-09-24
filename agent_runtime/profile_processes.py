"""The process-table seam behind profile delete and the desktop build-lock sweep (fork-only).

``hermes_cli.profiles`` re-imports ``_PROCESS_LISTER`` so its readers and every
``monkeypatch.setattr(profiles, "_PROCESS_LISTER", ...)`` see one name. Upstream
reads ``psutil`` inline; the seam is what lets the hermetic suite hand every
test an empty table instead of the operator's live one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Mapping, Optional, Protocol, Tuple


@dataclass(frozen=True)
class _ProcessFacts:
    """The per-process view this module's process consumers actually read.

    ``read_environ`` stays a callable rather than an already-materialized
    mapping because the environment read is the expensive, refusable half: it
    is consulted only for a process whose argv did not already answer the
    binding question.  Materializing it for every process would turn a rare
    read into a per-process one, so the laziness is part of the behaviour.

    Fields are optional because different consumers need different columns and
    a lister only pays for the ones its caller reads — ``psutil.process_iter``
    is priced per requested attribute.  Profile-delete asks for
    username/cmdline/environ; the desktop build-lock sweep
    (``hermes_cli.main._stop_desktop_processes_locking_build``) asks for
    ``exe``.  One row type, one lister protocol, one table — a second
    per-process view would be a second seam to keep honest.

    ``inspector_handle`` is the inspector's OWN object for this row, carried so
    a caller that must ACT on the process (terminate/kill/wait) does not have
    to re-resolve the pid afterwards.  Re-resolving is how pid-recycle bugs are
    born: between the walk and the act, the number can belong to something
    else.  It is ``None`` for a lister that has no such object to offer, and a
    reading caller never touches it.
    """

    pid: int
    username: Optional[str] = None
    cmdline: Tuple[str, ...] = ()
    read_environ: Optional[Callable[[], Mapping[str, str]]] = None
    exe: Optional[str] = None
    inspector_handle: Optional[object] = None

    def environ(self) -> Mapping[str, str]:
        """This process's environment, or ``{}`` when there is no reader.

        May raise: a live reader can refuse (``AccessDenied``) even for a
        same-user process.  The caller treats a refusal exactly as it treats
        an empty environment — no binding signal — and says so at that site.
        """
        if self.read_environ is None:
            return {}
        return self.read_environ() or {}

@dataclass(frozen=True)
class _ProcessTable:
    """One reading of the process table, as this module consumes it.

    Identity travels WITH the rows on purpose: "which pid am I", "who are my
    ancestors" and "which user am I" are answers about the same table, and a
    caller that got its rows from a fake while asking the live machine who it
    is would be filtering driven rows through undriven facts.
    """

    self_pid: int
    ancestor_pids: frozenset
    current_username: Optional[str]
    processes: Iterable[_ProcessFacts]

class _ProcessLister(Protocol):
    """Where ``hermes_cli.profiles._profile_bound_backend_pids`` gets its processes."""

    def read(self) -> Optional[_ProcessTable]:
        """One reading, or ``None`` when the table cannot be inspected at all."""
        ...

class _PsutilProcessLister:
    """The production lister: the live OS process table, via ``psutil``."""

    def read(self) -> Optional[_ProcessTable]:
        try:
            import psutil  # type: ignore
        except Exception:
            # No inspector on this machine.  The caller answers "no bound
            # backends" — unchanged from before this seam existed.
            return None

        self_pid = os.getpid()

        # Never terminate ourselves or a parent (e.g. `hermes -p <canon>
        # profile delete` runs under the very profile it's deleting).
        ancestors: set[int] = set()
        try:
            parent = psutil.Process(self_pid).parent()
            while parent is not None:
                ancestors.add(parent.pid)
                parent = parent.parent()
        except Exception:
            pass

        try:
            current_username: Optional[str] = psutil.Process(self_pid).username()
        except Exception:
            current_username = None

        return _ProcessTable(
            self_pid=self_pid,
            ancestor_pids=frozenset(ancestors),
            current_username=current_username,
            processes=self._iter_processes(psutil),
        )

    @staticmethod
    def _iter_processes(psutil) -> Iterator[_ProcessFacts]:
        """Yield lazily: the caller stops reading as soon as it has its answer."""
        for proc in psutil.process_iter(["pid", "name", "username", "cmdline"]):
            try:
                info = proc.info
                pid = info.get("pid")
                if pid is None:
                    continue
                yield _ProcessFacts(
                    pid=pid,
                    username=info.get("username"),
                    cmdline=tuple(info.get("cmdline") or ()),
                    read_environ=proc.environ,
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

_PROCESS_LISTER: _ProcessLister = _PsutilProcessLister()
