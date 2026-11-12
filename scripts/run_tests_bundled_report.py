"""What a bundled run prints: the per-file progress lines, the expected-wall plan line and the
closing summary (leaks, deaths, flakes, failure output, the NO TESTS RAN guard).

Moved out of ``scripts/run_tests_bundled.py`` (FH-SIZE-CEILING-TWO-FILES-OVER-800: the runner was
833 code lines against the 800 ceiling); the runner re-exports ``_print_summary``,
``_print_expected_wall`` and ``_progress_printer`` under their old names. Loaded by the runner's
``_load_sibling`` after its siblings, so the plain imports below resolve to the modules it
already loaded (``scripts/`` is not a package).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional, Sequence

import run_tests_bundled_diag as diag  # registered by run_tests_bundled._load_sibling
import run_tests_bundled_plan as plan
import run_tests_parallel as rtp
from run_tests_bundled_events import _CATEGORIES

def _rel(path: Path, repo_root: Path) -> str:
    return Path(rtp._format_file(path, repo_root)).as_posix()


def print_summary(
    result, files: Sequence[Path], repo_root: Path, elapsed: float, jobs: int, cost: Optional[dict] = None
) -> int:
    totals = {k: 0 for k in _CATEGORIES}
    failures = [o for o in result.outcomes if o.rc != 0]
    for outcome in result.outcomes:
        for key in _CATEGORIES:
            totals[key] += outcome.summary.get(key, 0)
    collected = sum(totals.values())
    crashed = sum(1 for o in result.outcomes if o.summary.get("crashed"))
    print()
    print(
        f"=== Summary: {len(files)} files ({len(result.bundles) - result.rebundles} bundles + "
        f"{result.rebundles} re-bundled, {len(result.solos)} solo, "
        f"{result.reruns} re-run alone), {totals['passed']} tests passed, {totals['failed']} failed, "
        f"{totals['errors']} errors, {totals['skipped']} skipped in {elapsed:.1f}s ({jobs} workers) ==="
    )
    if result.bundle_walls:
        walls = sorted(result.bundle_walls, key=lambda item: item[1], reverse=True)
        print("  Slowest bundles:")
        for index, wall, rc in walls[:10]:
            first = _rel(result.bundles[index][0], repo_root)
            print(f"    {wall:>7.1f}s  rc={rc}  #{index} ({len(result.bundles[index])} files from {first})")
    if cost:
        print()
        print("\n".join(plan.render(cost)))
        for line in diag.render(result.ledger.diagnosis if result.ledger is not None else None):
            print(line)
    if result.ledger is not None:
        for line in plan.render_bundle_diagnostics(result.ledger.bundle_diagnostics):
            print(line)
    leaks = [leak for leak in result.leaks if leak.kind == "leak"]
    unreached = [leak for leak in result.leaks if leak.kind == "unreached"]
    abnormal = [leak for leak in result.leaks if leak.kind == "abnormal-exit"]
    if abnormal:
        print()
        print(
            f"=== {len(abnormal)} member(s) of an abnormally ended bundle recorded no failure there and passed alone "
            "— NOT isolation leaks; the bundle diagnostics above carry the abnormal exit ==="
        )
        for leak in abnormal:
            print(f"  {_rel(leak.file, repo_root)}  # observed: bundle #{leak.bundle_index} {leak.in_bundle}; passed alone")
    if leaks:
        print()
        print(
            f"=== ⚠ {len(leaks)} ISOLATION LEAK{'S' if len(leaks) != 1 else ''} "
            "(red in a bundle that finished, green alone — candidates for scripts/test_bundles_unbundled.txt) ==="
        )
        for leak in leaks:
            print(
                f"  {_rel(leak.file, repo_root)}  # observed: bundle #{leak.bundle_index} {leak.in_bundle} "
                f"after {len(leak.earlier)} earlier member(s); passed alone"
            )
            for nodeid in leak.failed_nodeids[:5]:
                print(f"      red in bundle: {nodeid}")
            if leak.earlier:
                print(f"      earlier members: {', '.join(leak.earlier)}")
    if result.deaths:
        passed_alone = {_rel(leak.file, repo_root) for leak in unreached}
        print()
        print(
            f"=== {len(result.deaths)} bundle process(es) died before their session ended. The file each died in "
            "ran alone; the members behind it were re-bundled. The file is the unbundled-list candidate ==="
        )
        for death in sorted(result.deaths, key=lambda d: d.bundle_index):
            alone = "passed alone" if death.stopped_in in passed_alone else "red alone too"
            print(
                f"  {death.stopped_in}  # observed: bundle #{death.bundle_index} died in this file ({alone}); "
                f"{len(death.unreached)} later member(s) re-bundled"
            )
    if rtp._FLAKY_RESULTS:
        print()
        print(f"=== ⚠ {len(rtp._FLAKY_RESULTS)} FLAKY file(s) (failed once alone, passed on retry) ===")
        for path, _output in rtp._FLAKY_RESULTS:
            print(f"  {_rel(path, repo_root)}")
    if failures:
        print()
        print("=== Failure output ===")
        for outcome in sorted(failures, key=lambda o: _rel(o.file, repo_root)):
            print()
            print(f"--- {_rel(outcome.file, repo_root)} ---")
            print(outcome.output.rstrip())
        print()
        print(f"=== {len(failures)} file{'s' if len(failures) != 1 else ''} failed ===")
        for outcome in sorted(failures, key=lambda o: _rel(o.file, repo_root)):
            print(f"  {_rel(outcome.file, repo_root)}  {outcome.summary}")
    if collected == 0 and not crashed:
        print()
        print(f"=== ✗ NO TESTS RAN — 0 collected across {len(files)} files. This is NOT a pass. ===")
        return 1
    return 1 if failures else 0


def print_expected_wall(to_run, repo_root: Path, durations: dict[str, float], jobs: int, estimate: float) -> None:
    """The plan line that says how long the run will take; ``estimate`` is a file with no cached duration's."""
    _wall, line = plan.expected_wall(
        {_rel(f, repo_root): durations.get(rtp._format_file(f, repo_root)) for f in to_run},
        jobs, estimate,
    )
    print(line, flush=True)


def progress_printer(total: int, repo_root: Path, pytest_args: list[str]) -> Callable[[object], None]:
    """One ``[n/total]`` line per finished file, a failure's tail printed inline; thread-safe."""
    done = 0
    counter_lock = threading.Lock()

    def _progress(outcome) -> None:
        nonlocal done
        with counter_lock:
            done += 1
            status = "✓" if outcome.rc == 0 else "✗"
            print(
                f"[{done:>5}/{total}] {status} {_rel(outcome.file, repo_root)} "
                f"({outcome.via}, {outcome.seconds:.1f}s) {outcome.summary}",
                flush=True,
            )
            if outcome.rc != 0:
                rtp._print_inline_failure(outcome.file, outcome.output, repo_root, pytest_args)

    return _progress
