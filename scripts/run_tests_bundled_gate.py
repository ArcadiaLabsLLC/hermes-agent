"""The green-result cache wired into the bundled runner (fast-gate §1).

``scripts/run_tests_bundled.py::main`` makes one :class:`GateRun` per run: it
adds the dependency recorder to every pytest process the run spawns, and after
the run writes what each file depended on to the store
(``scripts/run_tests_bundled_cache.py``) and prints the census line.

Loaded by the runner's ``_load_sibling`` after its siblings, so the plain
imports below resolve to the modules it already loaded (``scripts/`` is not a
package; run as a script, it is ``sys.path[0]``).

Opt-out: ``--no-cache`` or ``HERMES_GATE_CACHE=0`` — no recorder, no store reads
or writes for the cache (the run record and durations still go to the store).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Mapping, Optional

import run_tests_bundled_cache as cache  # noqa: E402 — registered by run_tests_bundled._load_sibling
import run_tests_bundled_plan as plan  # noqa: E402

FLAGS = frozenset({"--no-cache", "--cache-dir"})
CACHE_ENV = "HERMES_GATE_CACHE"
PLUGIN_NAME = "hermes_dep_record"


def add_arguments(parser) -> None:
    parser.add_argument(
        "--no-cache", action="store_true",
        help="green-result cache off for this run: no dependency recording, no cached skips (or HERMES_GATE_CACHE=0)",
    )
    parser.add_argument(
        "--cache-dir", default=None,
        help=f"the gate store (default <primary checkout>/{cache.STORE_SUBDIR.as_posix()}, or ${cache.STORE_ENV})",
    )


class GateRun:
    """One run's side of the cache: the recorder's arguments, and what the run
    leaves in the store."""

    def __init__(self, store: "cache.GateStore", enabled: bool, deps_dir: Optional[Path]) -> None:
        self.store = store
        self.enabled = enabled
        self.deps_dir = deps_dir
        self.run_id = f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        self.collector = cache.DepsCollector(deps_dir) if deps_dir is not None else None

    @classmethod
    def start(cls, args, repo_root: Path, environ: Mapping[str, str] = os.environ) -> "GateRun":
        enabled = not getattr(args, "no_cache", False) and environ.get(CACHE_ENV, "1") != "0"
        override = getattr(args, "cache_dir", None) or environ.get(cache.STORE_ENV)
        store = cache.GateStore(cache.gate_store_dir(repo_root, plan.primary_checkout(repo_root), override))
        deps_dir = Path(tempfile.mkdtemp(prefix="gate-deps-")) if enabled else None
        return cls(store, enabled, deps_dir)

    @property
    def plugin_args(self) -> list:
        if not self.enabled:
            return []
        return ["-p", PLUGIN_NAME, f"--hermes-gate-deps={self.deps_dir}"]

    def report(self, result, rc: int) -> int:
        """After the Summary: persist the run's dependency records and print the
        census. Returns the run's exit code."""

        if not self.enabled or self.collector is None:
            print("  green-result cache: off (--no-cache / HERMES_GATE_CACHE=0)")
            return rc
        entries = self.collector.poll()
        self.store.write_deps(entries, self.run_id)
        seconds = result.ledger.file_seconds if result.ledger is not None else {}
        print(cache.census(entries, seconds))
        shutil.rmtree(self.deps_dir, ignore_errors=True)
        return rc
