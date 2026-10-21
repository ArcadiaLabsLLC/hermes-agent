"""The machine-wide heavy-run slot, claimed by the bundled runner.

The launcher's ``tool/heavy_run/slot_lock.dart`` caps how many HEAVY runs this
box serves at once (default 2): N lock files ``slot-<i>.lock`` in one
per-machine directory, each claimed by an OS byte-range lock over byte 0 and
carrying a JSON note (``pid``, ``label``, ``cwd``, ``since``) from byte 1 on.
A hermes suite that claims nothing runs 12 workers beside two launcher lanes
already asking for 14 each (row ``FORK-HERMES-TEST-ENTRY-POINTS``, owner ruling
2026-10-21: ``scripts/run_tests_bundled.py`` claims the launcher's slot).

This module speaks that file contract, byte for byte, so a Dart waiter names a
hermes holder and a hermes waiter names a Dart one:

* ``ETERNIA_HEAVY_SLOTS`` — the slot count (default 2; ``off``/``none``/``0``/
  garbage: no cap — a malformed variable never refuses a run);
* ``ETERNIA_HEAVY_SLOT_DIR`` — the directory, else ``<machine temp>/eternia-heavy-slots``.
  ``scripts/_fork_test_env.sh::fork_test_tmp_root`` exports it from the
  machine temp BEFORE it points TEMP at the test-tmp root, so the runner inside
  ``env -i`` still finds the launcher's directory;
* ``ETERNIA_HEAVY_SLOT_HELD`` — set in every child by a holder; a run that
  inherits it claims nothing (re-entrancy: a launcher ``heavy_run`` wrapper
  around this runner has already paid);
* ``ETERNIA_HEAVY_SLOT_JOBS`` — the advisory share-aware ``-j``, exported for
  the record and printed by a waiter; nothing lowers its workers on it.

The lock is the kernel's (``msvcrt.locking`` / ``fcntl.lockf`` over byte 0),
never a pid in a file: a killed holder frees its slot with no reaper.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional

COUNT_VAR = "ETERNIA_HEAVY_SLOTS"
DIR_VAR = "ETERNIA_HEAVY_SLOT_DIR"
HELD_VAR = "ETERNIA_HEAVY_SLOT_HELD"
JOBS_VAR = "ETERNIA_HEAVY_SLOT_JOBS"
DEFAULT_SLOTS = 2
DIR_NAME = "eternia-heavy-slots"
REPORT_EVERY_SECONDS = 20.0
POLL_EVERY_SECONDS = 0.25
_CLAIM_BYTE = b"#"


def slot_count(environ: Mapping[str, str]) -> int:
    """How many slots this machine offers; 0 means no cap."""
    raw = (environ.get(COUNT_VAR) or "").strip().lower()
    if not raw:
        return DEFAULT_SLOTS
    try:
        parsed = int(raw)
    except ValueError:
        return 0
    return max(0, parsed)


def slot_directory(environ: Mapping[str, str]) -> Path:
    """``ETERNIA_HEAVY_SLOT_DIR``, else the machine temp's ``eternia-heavy-slots``."""
    override = (environ.get(DIR_VAR) or "").strip()
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / DIR_NAME


def slot_jobs(slots: int, processors: Optional[int] = None) -> int:
    """The Dart side's ``heavySlotJobs``: the advisory share-aware worker count."""
    cpus = processors or os.cpu_count() or 4
    solo = min(max(cpus - 2, 1), 14)
    if slots <= 1:
        return solo
    return max(4, min(solo, (cpus - 2) // slots))


def _lock_byte0(fd: int) -> bool:
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
    except OSError:
        return False
    return True


def _unlock_byte0(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.lockf(fd, fcntl.LOCK_UN, 1, 0)


@dataclass
class Holder:
    """A claimed slot; ``release`` gives it back, and so does process death."""

    index: int
    jobs: int
    waited: float
    path: Path
    _fd: int
    _released: bool = False

    def child_environ(self) -> dict[str, str]:
        return {HELD_VAR: str(self.index), JOBS_VAR: str(self.jobs)}

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        for step in (lambda: os.ftruncate(self._fd, 1), lambda: _unlock_byte0(self._fd), lambda: os.close(self._fd)):
            with contextlib.suppress(OSError):
                step()


def _try_claim(index: int, directory: Path, label: str, jobs: int, waited: float) -> Optional[Holder]:
    path = directory / f"slot-{index}.lock"
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    except OSError:
        return None
    if not _lock_byte0(fd):
        os.close(fd)
        return None
    note = json.dumps(
        {"pid": os.getpid(), "label": label, "cwd": os.getcwd(), "since": _dt.datetime.now().isoformat()},
        separators=(",", ":"),
    ).encode("utf-8")
    with contextlib.suppress(OSError):  # the claim is the lock; a lost note is a worse diagnostic only
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, _CLAIM_BYTE + note)
        os.ftruncate(fd, 1 + len(note))
    return Holder(index, jobs, waited, path, fd)


def read_notes(directory: Path, slots: int) -> list[str]:
    """Each slot's last holder, one line apiece, read from byte 1 on (never the locked byte)."""
    lines = []
    for index in range(slots):
        try:
            with open(directory / f"slot-{index}.lock", "rb") as handle:
                handle.seek(1)
                note = json.loads(handle.read().decode("utf-8"))
            lines.append(f"slot {index}: pid {note.get('pid', '?')}  {note.get('label', '?')}\n            in {note.get('cwd', '?')}")
        except (OSError, ValueError, AttributeError):
            lines.append(f"slot {index}: held (no note)")
    return lines


def acquire(
    label: str,
    environ: Optional[Mapping[str, str]] = None,
    *,
    log: Callable[[str], None] = print,
    poll_every: float = POLL_EVERY_SECONDS,
    report_every: float = REPORT_EVERY_SECONDS,
    give_up_after: Optional[float] = None,
) -> Optional[Holder]:
    """Claim one slot, waiting and naming the holders; ``None`` means run without one.

    ``None`` when the cap is off, when this process inherited a slot, when the
    directory cannot be made, or after ``give_up_after`` seconds — never a refusal.
    """
    env = os.environ if environ is None else environ
    if (env.get(HELD_VAR) or "").strip():
        return None
    count = slot_count(env)
    if count <= 0:
        return None
    directory = slot_directory(env)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"  note: heavy-run slots unavailable ({directory}: {exc}); running without a slot.")
        return None
    jobs = slot_jobs(count)
    started = time.monotonic()
    last_report: Optional[float] = None
    while True:
        waited = time.monotonic() - started
        for index in range(count):
            holder = _try_claim(index, directory, label, jobs, waited)
            if holder is not None:
                if last_report is not None:
                    log(f"  ✔ heavy-run slot {index} acquired after {int(waited)} s.")
                return holder
        if give_up_after is not None and waited >= give_up_after:
            log(f"  note: no heavy-run slot after {int(waited)} s; running without one rather than waiting longer.")
            return None
        if last_report is None or waited - last_report >= report_every:
            last_report = waited
            log(f"\n  ⏳ waiting for a heavy-run slot — all {count} are busy ({int(waited)} s so far).")
            for line in read_notes(directory, count):
                log(f"     {line}")
            log(f"     This is the machine-wide cap working, not this command hung. Slots: ${COUNT_VAR} (off disables), dir: {directory}.")
            log(f"     ${JOBS_VAR}={jobs} is the share-aware worker count.\n")
        time.sleep(poll_every)


@contextlib.contextmanager
def claimed(label: str, *, log: Callable[[str], None] = print) -> Iterator[Optional[Holder]]:
    """Hold a slot for the block; the children it spawns inherit ``ETERNIA_HEAVY_SLOT_HELD``."""
    holder = acquire(label, log=log)
    if holder is None:
        yield None
        return
    log(f"▶ heavy-run slot {holder.index} held ({holder.path.parent})")
    os.environ.update(holder.child_environ())
    try:
        yield holder
    finally:
        holder.release()
        for name in (HELD_VAR, JOBS_VAR):
            os.environ.pop(name, None)
