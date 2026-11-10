"""The daily run's suite list: every file ``scripts/run_tests.sh`` would discover, minus the skip list.

``scripts/daily_full_run.sh``'s ``suite`` step runs the whole fork suite once a day
(FH-DAILY-FULL-RUN). The upstream skip list (``tests/fixtures/upstream_skip_list.txt``) holds the
upstream files the fork does not run in ANY scope: the P0 freeze files (run only under a
watchdog/VM), proven upstream/env reds, and the ADR 0015 ``unused`` features. The bundled runner
honours it; the per-file runner the daily step drives does not. A bare ``run_tests.sh`` ran all 902
listed files on 2026-11-08 and reported 12 of them red (row FH-W1108C-WAVE-END-REDS).

Usage: ``python scripts/daily_suite_files.py <list-out>``. Writes the kept files, one repo-relative
POSIX path per line, to ``<list-out>`` (the runner reads it with ``--files-from``), prints one
``--deselect=<path::node>`` per NODE row on stdout (a node row keeps its file in the run), and a
one-line count on stderr. Exit 2 on usage, or when the skip list is missing: without it the P0
files would silently be back in the run.

Discovery is the upstream runner's own (``run_tests_parallel._discover_files`` over ``tests``) and
the rows are the bundled runner's own parser (``run_tests_bundled_plan.load_skip_list``), so the
daily run, a bare ``run_tests.sh`` and a landing cannot disagree on what a row means. Filtering a
7,996-file list through ``--ignore`` instead costs the runner 176 s (its per-flag path match).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = _SCRIPTS.parent


def suite_plan(repo_root: Path = REPO_ROOT) -> tuple[list[str], list[str], int]:
    """``(kept files, --deselect args, files the skip list kept out)``."""

    if str(_SCRIPTS) not in sys.path:  # ``scripts/`` is not a package; its modules import siblings by name
        sys.path.insert(0, str(_SCRIPTS))
    import run_tests_bundled_plan as plan
    import run_tests_parallel as rtp

    rows = plan.load_skip_list(repo_root / plan.SKIP_LIST)
    listed = {row.file for row in rows.values() if not row.node}
    kept: list[str] = []
    dropped = 0
    for path in rtp._discover_files([repo_root / "tests"]):
        rel = path.relative_to(repo_root).as_posix()
        if rel in listed:
            dropped += 1
        else:
            kept.append(rel)
    deselects = [f"--deselect={row.path}" for row in rows.values() if row.node]
    return kept, deselects, dropped


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: daily_suite_files.py <list-out>", file=sys.stderr)
        return 2
    try:
        kept, deselects, dropped = suite_plan()
    except (OSError, ValueError) as exc:
        print(f"daily_suite_files: cannot read the skip list: {exc}", file=sys.stderr)
        return 2
    Path(argv[0]).write_text("".join(f"{rel}\n" for rel in kept), encoding="utf-8", newline="\n")
    for arg in deselects:
        print(arg)
    print(f"daily_suite_files: {len(kept)} file(s); the skip list keeps out {dropped} file(s) and "
          f"deselects {len(deselects)} node(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
