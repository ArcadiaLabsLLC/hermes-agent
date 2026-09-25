"""The ONE-OWNER lock for a runtime root's socket lane: the lock file, the owner
record, the drain handshake, and the platform byte-range lock primitives.

``SocketOwnerLock`` decides which serve runs the lane; ``read_socket_owner``
is how a client reads the record it publishes.
"""

from __future__ import annotations

import errno
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
if os.name == "nt":  # pragma: no cover - platform split, both sides exercised in CI
    import msvcrt
else:  # pragma: no cover - platform split
    import fcntl

from agent_runtime.serde import write_json_atomic

from agent_runtime.serve_socket.vocabulary import (
    LOCK_OUTCOME_ACQUIRED,
    LOCK_OUTCOME_HELD,
    OWNER_STATE_ABSENT,
    OWNER_STATE_DEAD,
    OWNER_STATE_LIVE,
    OWNER_STATE_LIVENESS_UNKNOWN,
    OWNER_STATE_MALFORMED,
    OWNER_STATE_PID_MISSING,
    OWNER_STATE_SELF,
    OWNER_STATE_UNREADABLE,
    SOCKET_LOCK_DRAIN_POLL_SECONDS,
    SOCKET_LOCK_DRAIN_WAIT_SECONDS,
    SOCKET_LOCK_FILENAME,
    SOCKET_OWNER_DRAINING_KEY,
    SOCKET_OWNER_FILENAME,
)
from agent_runtime.serve_socket.wire import _int_or_none, _now_iso, _os_error_token

__layer__ = "stores"

__all__ = [
    "SocketLockResult",
    "SocketOwnerLock",
    "_LockUnavailable",
    "_lock_first_byte",
    "_owner_pid_alive",
    "_read_owner_record",
    "_text_or_none",
    "_unlock_first_byte",
    "read_socket_owner",
    "socket_lock_path",
    "socket_owner_path",
]


# ── the one-owner lock ───────────────────────────────────────────────────────


def socket_lock_path(store_root: Path | str) -> Path:
    return Path(store_root) / SOCKET_LOCK_FILENAME


def socket_owner_path(store_root: Path | str) -> Path:
    return Path(store_root) / SOCKET_OWNER_FILENAME


@dataclass(frozen=True, slots=True)
class SocketLockResult:
    """Who owns the socket lane for this root, and how we know."""

    #: ``acquired`` | ``lock_held_by`` | ``error:<reason>``
    outcome: str
    #: The CURRENT holder's pid when known — ours on ``acquired``, the winner's
    #: (from the sidecar) on ``lock_held_by``, None when the sidecar is absent.
    pid: int | None
    path: str
    #: The sidecar's ``started_at`` for the pid named in :attr:`pid` /
    #: :attr:`took_over_from`. On ``lock_held_by`` it is how a launcher tells
    #: "the same incumbent I saw last time" from "a fresh one"; on a takeover it
    #: is when the corpse had booted. None when the sidecar did not say.
    owner_started_at: str | None = None
    #: R-L2. The pid of the PREVIOUS owner whose advertisement this process
    #: replaced, and it appears only when that pid was PROVEN not running. Never
    #: set on the ordinary uncontested boot (no sidecar, or our own).
    took_over_from: int | None = None
    #: RS-4. Milliseconds this process spent waiting for an owner it could prove
    #: was LEAVING, and it appears on both endings: on ``acquired`` it is how
    #: long the takeover cost, on ``lock_held_by`` it is how long the incumbent
    #: was given before the degrade. Absent (None) when no wait was entered at
    #: all, which is every ordinary boot and every refusal by a healthy owner —
    #: so "the key is missing" and "the key is 0" mean different things and
    #: neither is a guess.
    waited_for_drain_ms: int | None = None
    #: One of the ``OWNER_STATE_*`` words: what the pre-existing sidecar was.
    #: Diagnostic — it never reaches a greeting frame (see :meth:`payload`).
    owner_state: str = OWNER_STATE_ABSENT

    @property
    def acquired(self) -> bool:
        return self.outcome == LOCK_OUTCOME_ACQUIRED

    def payload(self) -> dict[str, Any]:
        """The three keys this block has always had, plus the two R-L2 facts.

        Additive and absent-when-unknown, deliberately: a reader written against
        the three-key block finds exactly those three unchanged, and a reader
        that learned ``took_over_from`` can tell "this serve inherited a dead
        owner's lane" from "this serve booted into an empty root" — which is the
        difference between a launcher reporting a recovered restart and a
        launcher reporting nothing at all. ``owner_state`` is deliberately NOT
        here; it is a debugging word, and the wire gets outcomes.
        """

        row: dict[str, Any] = {
            "outcome": self.outcome,
            "pid": self.pid,
            "path": self.path,
        }
        if self.owner_started_at is not None:
            row["owner_started_at"] = self.owner_started_at
        if self.took_over_from is not None:
            row["took_over_from"] = self.took_over_from
        if self.waited_for_drain_ms is not None:
            row["waited_for_drain_ms"] = self.waited_for_drain_ms
        return row


class SocketOwnerLock:
    """An exclusive OS lock held for the life of the process.

    Non-blocking against a HEALTHY holder, by design. A serve that loses this
    race has a job to do (stdio) and must not spend its boot waiting for a lock
    whose holder is not going anywhere — the loser degrades loudly instead.
    Against a holder it can prove is LEAVING it does wait, bounded; see "A
    LEAVING owner is worth waiting for" below.

    A DEAD owner is not a holder (R-L2)
    -----------------------------------

    The window this closes was measured on the operator's machine on
    2026-09-04: the launcher killed the old serve child and respawned without
    awaiting its exit, the replacement's ``acquire()`` answered ``lock_held_by``
    naming pid 25672, and 25672 was gone. The replacement then ran stdio-only
    for the rest of the session — no socket lane, and therefore (``serve.py``)
    no LAN listener either, which is how a toggle that had written its config
    correctly produced a door that never opened.

    **The OS lock is not the stale part; the SIDECAR is.** Both
    ``msvcrt.locking`` and ``flock`` are released by the kernel when the holding
    process dies, so a sidecar naming a corpse cannot describe the current
    holder of a lock that is still held. There are therefore exactly two shapes
    and this class answers both:

    * the lock is FREE and a sidecar from a dead owner is lying beside it — the
      ordinary crash/kill leftover. ``acquire()`` succeeds on the first try and
      records ``took_over_from``, so the takeover is a receipt rather than a
      silent overwrite of the previous owner's advertisement.
    * the lock is HELD and the sidecar names a dead pid — the exit is genuinely
      in flight (the corpse's handle has closed a hair before or after the
      probe, or the sidecar was never rewritten). One retry, and one only: a
      lock we could not take on the second attempt is held by something the
      sidecar does not describe, and this class does not spin.

    What it does NOT do is take a lock away from a live owner that is SERVING.
    That refusal is unchanged, byte for byte — ``lock_held_by`` with the
    winner's pid, on the first attempt, without a poll — because the whole point
    of the lock is that "connect to the service for root X" has one answer.

    A LEAVING owner is worth waiting for (RS-4)
    -------------------------------------------

    Measured on the operator's machine on 2026-09-07, and it is the R-L2 defect
    with the pid alive: a build-behind restart drained the old runtime, the
    replacement asked for the lock 14 s into that drain, and got
    ``lock_held_by`` naming a process whose listener had ALREADY closed. The
    order is not the bug — the drain releases this lock before it drops its
    registry row — but the release is the last act of a shutdown that first
    waits out every in-flight request, and for that whole window the holder is
    alive, holding, and finished. The replacement ran stdio-only for the rest of
    the session: no socket, no hub stream, no LAN listener, "bridge stopped" on
    the operator's sheet.

    So there is a THIRD shape, and it is separated from a healthy incumbent by
    evidence rather than by a timer:

    * the lock is HELD, the sidecar names a LIVE pid, and that pid is provably
      on its way out — either ``draining_at`` is stamped on the sidecar (the
      owner said so itself, at drain start, before closing its listener) or the
      owner has no ``serve_instances/<pid>.json`` row (it already unregistered).
      :meth:`acquire` then polls the lock every
      :data:`SOCKET_LOCK_DRAIN_POLL_SECONDS` for at most
      :data:`SOCKET_LOCK_DRAIN_WAIT_SECONDS` and takes the lane when it frees,
      recording ``took_over_from`` and ``waited_for_drain_ms``.

    A wait that expires degrades exactly as it always did, and carries the
    number: the difference between "it never tried" and "it gave the incumbent
    25 s" is the difference between a defect and a drain that outlived its own
    deadline. An unreadable sidecar and an unanswerable liveness probe are NOT
    leaving — the fail-safe direction is the same as :meth:`_classify_owner`'s,
    because waiting on a hunch spends a boot.
    """

    def __init__(
        self,
        store_root: Path | str,
        *,
        log: Callable | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store_root = Path(store_root)
        self._path = socket_lock_path(store_root)
        self._owner_path = socket_owner_path(store_root)
        self._handle = None
        self._acquired = False
        self._lock = threading.Lock()
        self._log = log
        # Injected for the same reason :class:`HelloRateLimiter` injects its
        # own: the bound under test is 25 REAL seconds, and a test that waited
        # them out could not tell "it acquired because the owner left" from "it
        # acquired because something else did". Production passes neither.
        self._clock = clock
        self._sleep = sleep

    @property
    def path(self) -> Path:
        return self._path

    def acquire(self) -> SocketLockResult:
        with self._lock:
            if self._acquired:
                return SocketLockResult(
                    outcome=LOCK_OUTCOME_ACQUIRED,
                    pid=os.getpid(),
                    path=str(self._path),
                    owner_state=OWNER_STATE_SELF,
                )
            # READ THE SIDECAR FIRST. This is the only moment the previous
            # owner's identity is still on disk: `publish_owner` overwrites it
            # a few lines later in the caller, and after that nothing can say
            # whose lane this used to be.
            owner, owner_state = self._classify_owner()
            owner_pid = _int_or_none(owner.get("pid"))
            owner_started_at = _text_or_none(owner.get("started_at"))

            handle, failure = self._try_lock()
            if handle is None and failure is None and owner_state == OWNER_STATE_DEAD:
                # The one retry. See the class docstring: a lock whose sidecar
                # names a proven-dead pid is a lock in the act of being
                # released, and the kernel has already done the releasing.
                handle, failure = self._try_lock()
            waited_ms: int | None = None
            if (
                handle is None
                and failure is None
                and self._owner_is_leaving(owner, owner_state, owner_pid)
            ):
                # RS-4. The owner is alive, so the branch below would refuse —
                # but it is alive and LEAVING, and refusing a lane whose holder
                # is on its way out is what cost the operator a whole session
                # on 2026-09-07: the replacement ran stdio-only, so no socket,
                # no hub stream, and no LAN listener for the rest of the day.
                handle, failure, waited_ms = self._wait_for_drain()
            if handle is None:
                if failure is None:
                    # RE-READ before naming the winner, which is what this
                    # branch did before the takeover rule existed and must keep
                    # doing: the incumbent publishes its sidecar just after it
                    # takes the lock, so the copy read above can predate the
                    # very process that beat us. The read-first copy exists for
                    # the takeover receipt; the freshest copy is what a loser
                    # reports.
                    owner, owner_state = self._classify_owner()
                    owner_pid = _int_or_none(owner.get("pid"))
                    owner_started_at = _text_or_none(owner.get("started_at"))
                result = SocketLockResult(
                    outcome=(
                        LOCK_OUTCOME_HELD if failure is None else f"error:{failure}"
                    ),
                    pid=owner_pid if failure is None else None,
                    path=str(self._path),
                    owner_started_at=(
                        owner_started_at if failure is None else None
                    ),
                    waited_for_drain_ms=waited_ms,
                    owner_state=owner_state,
                )
                self._note(result, owner_pid=owner_pid)
                return result

            self._handle = handle
            self._acquired = True
            # A takeover is now either of two proofs that the previous owner is
            # not coming back: it was already dead when we looked, or it let go
            # of the lock while we waited on its drain. The receipt is the same
            # word because the launcher's question is the same one — "did this
            # boot inherit somebody's lane, and whose".
            took_over = (
                owner_pid
                if (owner_state == OWNER_STATE_DEAD or waited_ms is not None)
                else None
            )
            result = SocketLockResult(
                outcome=LOCK_OUTCOME_ACQUIRED,
                pid=os.getpid(),
                path=str(self._path),
                owner_started_at=owner_started_at if took_over is not None else None,
                took_over_from=took_over,
                waited_for_drain_ms=waited_ms,
                owner_state=owner_state,
            )
            self._note(result, owner_pid=owner_pid)
            return result

    # ── acquire's helpers ───────────────────────────────────────────────────

    def _owner_is_leaving(
        self, owner: dict[str, Any], owner_state: str, owner_pid: int | None
    ) -> bool:
        """Is the live holder of this lock on its way OUT? (RS-4)

        Two independent proofs, either of which is enough, and neither of which
        is a guess about a process this one cannot see:

        * the sidecar carries :data:`SOCKET_OWNER_DRAINING_KEY` — the owner
          stamped it itself, as the first act of its drain, before it closed its
          listener (``hermes_cli/harness_parts/serve/boot_phases.py``);
        * the owner's registry row is GONE. ``_finish_drain`` unregisters as the
          statement after it releases this lock, and nothing else removes a live
          serve's row, so a live pid with no row is a serve inside the last
          breath of its shutdown.

        Everything else is refused as before. In particular a sidecar we could
        not read, or one naming a pid whose liveness the probe could not answer,
        is NOT leaving: waiting on those would spend a boot on a hunch, and the
        fail-safe direction here is the same as :meth:`_classify_owner`'s.
        """

        if owner_state != OWNER_STATE_LIVE or owner_pid is None:
            return False
        if _text_or_none(owner.get(SOCKET_OWNER_DRAINING_KEY)) is not None:
            return True
        return not self._owner_register_row_exists(owner_pid)

    def _owner_register_row_exists(self, owner_pid: int) -> bool:
        """``<store_root>/serve_instances/<pid>.json``, asked of the registry.

        Imported rather than joined by hand for the same reason
        :func:`_owner_pid_alive` is: the layout of that directory is the
        registry's to decide, and a second spelling of the path here would be a
        second thing to keep true. An unreadable answer counts as PRESENT, which
        is the conservative direction — it declines the wait.
        """

        try:
            from ..serve_registry import serve_instance_path

            return serve_instance_path(self._store_root, owner_pid).exists()
        except Exception:  # noqa: BLE001 — a probe never fails a boot
            return True

    def _wait_for_drain(self) -> tuple[Any, str | None, int]:
        """Poll the OS lock until the leaving owner frees it, or the bound ends.

        Returns ``(handle, failure, waited_ms)`` — the same two-value answer
        :meth:`_try_lock` gives, plus the number that makes both endings
        readable. It polls the LOCK and never re-reads the sidecar: the sidecar
        is what got us into this loop, and the only fact that can end it is the
        kernel's.

        The sleep comes FIRST. A lock we just failed to take microseconds ago
        will not have freed in between, and an immediate re-try would only make
        the first lap a duplicate of the attempt that sent us here.
        """

        started = self._clock()
        while True:
            self._sleep(SOCKET_LOCK_DRAIN_POLL_SECONDS)
            handle, failure = self._try_lock()
            waited_ms = int(round((self._clock() - started) * 1000.0))
            if handle is not None or failure is not None:
                return handle, failure, waited_ms
            if (self._clock() - started) >= SOCKET_LOCK_DRAIN_WAIT_SECONDS:
                return None, None, waited_ms

    def _try_lock(self) -> tuple[Any, str | None]:
        """``(handle, None)`` on success, ``(None, None)`` when CONTENDED, or
        ``(None, "<token>")`` when the filesystem itself refused.

        The three-way answer is what lets :meth:`acquire` retry a contended
        lock without retrying a broken directory: ``lock_held_by`` and
        ``error:EACCES`` are different facts and only one of them is worth a
        second attempt.
        """

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self._path, "a+b")
        except OSError as exc:
            return None, _os_error_token(exc)
        try:
            _lock_first_byte(handle)
        except _LockUnavailable:
            handle.close()
            return None, None
        except OSError as exc:
            handle.close()
            return None, _os_error_token(exc)
        return handle, None

    def _classify_owner(self) -> tuple[dict[str, Any], str]:
        """The pre-existing sidecar and one ``OWNER_STATE_*`` word for it.

        Liveness comes from ``serve_registry.pid_alive`` — the SAME probe that
        classifies a registry row ``stale_dead_pid``, imported rather than
        re-implemented, because a second answer to "is that pid alive" is a
        second answer that can drift. The fail-safe direction is the OPPOSITE of
        the registry's, and deliberately so: a probe that cannot answer lands on
        ``liveness_unreadable``, which is NOT a takeover. Guessing "dead" here
        would publish ``took_over_from`` about a process that is serving.
        """

        record, state = _read_owner_record(self._owner_path)
        if record is None:
            return {}, state or OWNER_STATE_ABSENT
        pid = _int_or_none(record.get("pid"))
        if pid is None or pid <= 0:
            return record, OWNER_STATE_PID_MISSING
        if pid == os.getpid():
            return record, OWNER_STATE_SELF
        alive = _owner_pid_alive(pid)
        if alive is None:
            return record, OWNER_STATE_LIVENESS_UNKNOWN
        return record, OWNER_STATE_LIVE if alive else OWNER_STATE_DEAD

    def _note(self, result: SocketLockResult, *, owner_pid: int | None) -> None:
        """One log line whenever the sidecar was anything but empty-or-ours.

        R-L2 asks for the takeover to be logged; the other states are here for
        the same money and answer the question an operator asks next. A
        malformed sidecar beside a lock we took is worth a line precisely
        because the boot then LOOKS clean — nothing else would ever mention it.
        """

        if self._log is None or result.owner_state in (
            OWNER_STATE_ABSENT,
            OWNER_STATE_SELF,
        ):
            return
        try:
            self._log(
                {
                    "event": (
                        "serve_socket_owner_takeover"
                        if result.took_over_from is not None
                        else "serve_socket_owner_stale"
                    ),
                    "pid": os.getpid(),
                    "outcome": result.outcome,
                    "owner_state": result.owner_state,
                    "owner_pid": owner_pid,
                    "owner_started_at": result.owner_started_at,
                    # RS-4. On a takeover it says what the wait bought; on a
                    # refusal it says how long the incumbent was given before
                    # this runtime degraded, which is the difference between
                    # "it never tried" and "the drain outlasted the bound".
                    "waited_for_drain_ms": result.waited_for_drain_ms,
                    "path": result.path,
                }
            )
        except Exception:  # noqa: BLE001 — an instrument never fails a boot
            pass

    def publish_owner(self, record: dict[str, Any]) -> None:
        """Write the identity sidecar. Best effort; the LOCK is the authority."""

        if not self._acquired:
            return
        try:
            write_json_atomic(self._owner_path, dict(record))
        except Exception:
            pass

    def mark_draining(self, when: str | None = None) -> bool:
        """Stamp the sidecar ``draining_at``: this owner is LEAVING. (RS-3)

        Called as the first act of the drain, BEFORE the listener closes, so
        there is no window in which the lane refuses new connections while still
        advertising itself as a healthy owner — which is exactly the window a
        contender arrived in on 2026-09-07 and read as "serving".

        It REWRITES the published record rather than replacing it: the sidecar
        is still the discovery answer for the clients already attached, and a
        drain that blanked the port would turn one defect into two. Additive by
        construction, so a reader that predates this key finds the keys it
        knows, unchanged and in the same places.

        Best effort and never raises — a bookkeeping stamp that could fail a
        drain would be a worse defect than the one it exists to close. Returns
        True the one time it lands on disk.
        """

        if not self._acquired:
            return False
        try:
            record, _state = _read_owner_record(self._owner_path)
            row = dict(record or {})
            row.setdefault("pid", os.getpid())
            row[SOCKET_OWNER_DRAINING_KEY] = when or _now_iso()
            write_json_atomic(self._owner_path, row)
            return True
        except Exception:  # noqa: BLE001 — the drain outranks its own receipt
            return False

    def release(self) -> None:
        """Unlock, close, and drop the owner sidecar. Idempotent; never raises.

        The LOCK FILE ITSELF IS NEVER UNLINKED. It used to be, and on POSIX that
        is a two-owner race: ``flock`` is held on an OPEN DESCRIPTION, not on a
        path, so a contender that has already opened the file but not yet
        flocked it keeps a descriptor to an inode this release then unlinks —
        the contender locks a file that no longer has a name, the next boot
        creates a NEW inode at that path and locks that, and both processes hold
        an "exclusive" lock on the one root. A persistent zero-byte lock file is
        the standard pattern for exactly this reason, and it costs nothing: the
        lock's authority is the OS lock on the open file, never the file's
        existence, and :meth:`acquire` opens with ``a+b`` so a surviving file is
        re-lockable immediately.

        Windows behaviour is unchanged in substance (``msvcrt.locking`` is
        mandatory and released with the handle); it simply stops depending on an
        unlink that the AV/indexer can lose anyway.

        The owner SIDECAR is still removed: it is discovery data, it advertises
        a port this process no longer serves, and it holds no lock at all.
        """

        with self._lock:
            handle, self._handle = self._handle, None
            was_acquired, self._acquired = self._acquired, False
        if handle is not None:
            try:
                _unlock_first_byte(handle)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass
        if not was_acquired:
            return
        # Order matters on Windows: the handle above must be closed before the
        # sidecar's writer can be considered done with the directory.
        try:
            self._owner_path.unlink()
        except OSError:
            pass


def read_socket_owner(store_root: Path | str) -> dict[str, Any]:
    """The published owner sidecar for *store_root*, or ``{}``.

    Advisory by contract: the sidecar is how a client DISCOVERS the port, and
    how a lock loser names the winner. It is never proof of liveness — that is
    the registry's read-time classification, and the hello handshake's.
    """

    try:
        record, _state = _read_owner_record(socket_owner_path(store_root))
    except Exception:  # noqa: BLE001 — advisory data, never a raise
        return {}
    return record or {}


def _read_owner_record(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """``(record, None)`` when it parsed, ``(None, OWNER_STATE_*)`` when not.

    The reason word is the whole difference from :func:`read_socket_owner`,
    which collapses "no file" and "half a file" into the same ``{}``. That
    collapse is fine for discovery — either way there is no port to dial — and
    is exactly wrong for the lock, which has to be able to LOG that it took a
    lane while a corrupt sidecar sat beside it. One reader, two callers, so the
    parse rules cannot drift.
    """

    try:
        raw = path.read_bytes().decode("utf-8", "replace")
    except FileNotFoundError:
        return None, OWNER_STATE_ABSENT
    except OSError:
        return None, OWNER_STATE_UNREADABLE
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, OWNER_STATE_MALFORMED
    if not isinstance(parsed, dict):
        return None, OWNER_STATE_MALFORMED
    return parsed, None


def _owner_pid_alive(pid: int) -> bool | None:
    """ONE liveness question, asked of the module that already answers it.

    ``serve_registry.pid_alive`` is imported here rather than copied because it
    carries a hard-won prohibition — never ``os.kill(pid, 0)`` on Windows, where
    CPython routes signal 0 through ``GenerateConsoleCtrlEvent`` and the probe
    Ctrl-C's the target's console group (bpo-14484). A second implementation of
    this check is a second place for that to be got wrong. Lazily imported to
    keep this module's import graph flat, and ``None`` on any failure, which the
    caller reads as "no takeover".
    """

    try:
        from ..serve_registry import pid_alive

        return pid_alive(int(pid))
    except Exception:  # noqa: BLE001
        return None


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


# ── helpers ──────────────────────────────────────────────────────────────────


class _LockUnavailable(Exception):
    pass


def _lock_first_byte(handle) -> None:
    """Exclusive, NON-BLOCKING lock on byte 0 — the locks.py pattern.

    The file is padded to one byte first because ``msvcrt.locking`` cannot lock
    a region of an empty file.
    """

    if os.name == "nt":
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EDEADLK, 13, 36}:
                raise _LockUnavailable() from exc
            raise
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
            raise _LockUnavailable() from exc
        raise


def _unlock_first_byte(handle) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
