"""Fan a whole-tree census out over worker processes, per file, in file order.

The name census gates (``tests/tooling/test_no_ladder_routing.py``,
``tests/agent_runtime/test_duplicate_helper_bodies.py``) walk ~1,400 fork files in one
process: 62 s and 44 s wall at load ~30 on the 52-core Linux box (2026-11-08,
FH-PREPUSH-CAP-TIGHT), CPU-bound in ``ast`` the whole way. Each file's census row is a
pure function of the tree on disk, so the walk splits into contiguous chunks (a package's
files share their imports, so a worker reparses little) mapped over a process pool, and
the chunks' results come back in the order the serial walk produced them.

* :func:`census_jobs` — ``HERMES_CENSUS_JOBS`` (a whole number; ``1`` = serial), else
  ``min(8, cpu_count)``; a population under :data:`MIN_PARALLEL` files runs serially (the
  gates' tmp-tree fixtures: a pool's start costs more than their walk).
* :func:`map_chunks` — ``fn(chunk, *args)`` per chunk; ``fn`` and ``args`` must pickle
  (module-level functions, plain data). The default start method runs (``forkserver`` on
  Linux from Python 3.14, ``spawn`` on Windows and macOS), never a bare ``fork`` of a pytest
  process that holds threads: each worker imports ``fn``'s module afresh, and the caller's
  ``__main__`` is re-imported, so a caller is ``python -m pytest`` or a ``__main__``-guarded
  script (``scripts/god_file_probe.py`` is one).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")

#: Below this many files the walk stays in-process.
MIN_PARALLEL = 200
#: The default worker count: the census step runs its two gates side by side, under a
#: box that is usually busy with other lanes.
DEFAULT_JOBS = 8
#: Chunks per worker: enough to even out a slow package, few enough to keep locality.
CHUNKS_PER_JOB = 3


def census_jobs(items: int) -> int:
    """How many workers a census over ``items`` files uses (1 = in-process)."""
    raw = os.environ.get("HERMES_CENSUS_JOBS", "").strip()
    if raw:
        if not raw.isdigit() or int(raw) < 1:
            raise ValueError(f"HERMES_CENSUS_JOBS must be a positive whole number, not {raw!r}")
        jobs = int(raw)
    else:
        jobs = min(DEFAULT_JOBS, os.cpu_count() or 1)
    return 1 if items < MIN_PARALLEL else max(1, min(jobs, items))


def chunks(items: Sequence[T], parts: int) -> list[Sequence[T]]:
    """``items`` cut into ``parts`` contiguous runs (the last ones one shorter), order kept."""
    parts = max(1, min(parts, len(items)))
    size, extra = divmod(len(items), parts)
    out, start = [], 0
    for index in range(parts):
        end = start + size + (1 if index < extra else 0)
        out.append(items[start:end])
        start = end
    return [chunk for chunk in out if chunk]


def map_chunks(fn: Callable[..., R], items: Sequence[T], *args: object) -> list[R]:
    """``[fn(chunk, *args) for chunk in chunks(items)]``, on a pool when the census is big enough."""
    jobs = census_jobs(len(items))
    if jobs == 1:
        return [fn(items, *args)] if items else []
    parts = chunks(items, jobs * CHUNKS_PER_JOB)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(fn, part, *args) for part in parts]
        return [future.result() for future in futures]
