"""The resident snapshot worker: the read-model core is built in a child process.

Plan ``docs/agent-runtime-harness/planned/snapshot-offproc-2026-10-06.md`` stage S2.
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
