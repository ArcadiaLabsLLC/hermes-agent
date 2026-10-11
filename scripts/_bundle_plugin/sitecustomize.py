"""A Python child of a test records what it touched (fast-gate §1 stage 1b).

The bundled runner puts ``scripts/_bundle_plugin`` first on ``PYTHONPATH`` for
every process of a run, so every Python child that inherits the environment
imports this module at start-up. It does nothing unless the dependency recorder
(``hermes_dep_record``) exported all three of ``HERMES_GATE_CURRENT_FILE``,
``HERMES_GATE_CHILD_EVENTS`` and ``HERMES_GATE_ROOT`` in the test process that
spawned it. Then it installs the same audit trail, and at exit writes ONE line
to ``<HERMES_GATE_CHILD_EVENTS>/child-<pid>-<ns>.jsonl``::

    {"k": "child", "f": <the inherited test file>, "paths": [...], "dirs": [...],
     "spawn_py": <n>, "spawn_other": <n>, "mods": [...]}

A child started with ``-I``/``-E``/``-S``, with a scrubbed environment, killed
before exit or replaced by ``exec`` writes nothing; its parent's file then keeps
depending on the whole tree (the runner counts records against spawns). Every
failure here is swallowed: this module runs inside production processes under
test and must never change what they do.
"""


def _install() -> None:
    import os

    current = os.environ.get("HERMES_GATE_CURRENT_FILE")
    directory = os.environ.get("HERMES_GATE_CHILD_EVENTS")
    root = os.environ.get("HERMES_GATE_ROOT")
    if not (current and directory and root):
        return

    import atexit
    import json
    import sys
    import time

    from hermes_dep_trail import _SESSION, AuditTrail

    trail = AuditTrail(root)
    sys.addaudithook(trail.hook)

    def _write() -> None:
        trail.active = False
        try:
            bucket = trail.bucket(_SESSION)
            record = {"k": "child", "f": current,
                      "paths": sorted(bucket.paths), "dirs": sorted(bucket.dirs),
                      "spawn_py": bucket.spawn_py, "spawn_other": bucket.spawn_other,
                      "mods": sorted(trail.filter.modules())}
            path = os.path.join(directory, f"child-{os.getpid()}-{time.time_ns()}.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except Exception:  # noqa: BLE001 — never fail the child's exit
            return

    atexit.register(_write)


try:
    _install()
except Exception:  # noqa: BLE001 — never fail the child's start-up
    pass
