"""The resident snapshot worker: the read-model core is built in a child process.

Plan ``docs/agent-runtime-harness/archive/snapshot-offproc-2026-10-06.md`` stage S2.
The serve keeps every decision -- the consult, the coalescer, the roles, the ledger
span, the receipt, ``write_back`` and the reuse memos; only
``_build_snapshot_uncoalesced()`` moves (``executor.execute_build``), and a dead or
hung worker falls back to building in process for that request.

* ``worker`` -- spawn the child and the ``snapshot.subprocess_worker`` switch;
* ``peer`` -- the serve's end of the pipe (the ``native_peer`` frame codec);
* ``child`` -- the child's request loop; ``entry`` -- its ``-m`` main;
* ``executor`` -- the serve's binding: worker or in process, never a lost build.
"""

__layer__ = "models"
__all__ = ["is_reader_process", "mark_reader_process"]

#: True in the resident snapshot worker's own interpreter (set by ``entry.main``). The worker READS the
#: stores its serve resolved; the serve that spawned it owns their start-time migrations, so a plugin load
#: here (its builds load plugins per profile home) runs none of them
#: (``hermes_cli.harness_parts.start_time_setup``, w1122f-agentlist).
_READER_PROCESS = False


def mark_reader_process() -> None:
    """Mark this interpreter as the snapshot worker (process-wide, set once by ``entry.main``)."""

    global _READER_PROCESS
    _READER_PROCESS = True


def is_reader_process() -> bool:
    """Whether this interpreter is the resident snapshot worker."""

    return _READER_PROCESS
