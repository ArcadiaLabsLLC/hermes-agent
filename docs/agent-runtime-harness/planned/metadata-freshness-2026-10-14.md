# Package metadata freshness repair

The intermittent failure in `test_skill_root_freshness` was a production cache
defect, not bundle contamination. A native Windows probe repeated the test's
two-directory sequence 100 times: 81 reads retained one metadata directory
after a second existed. In those failures the parent directory's `mtime_ns`
was unchanged; its creation time and size did not distinguish the change either.

`hermes_cli/venv_integrity.py` now reads names through `os.scandir`, filters
metadata suffixes before checking entry types, and groups those current names.
The timestamp memo and its private relisting helper are removed. This stays
inside the existing integrity owner, with no watcher, expiry policy or second
cache. Unavailable-directory behavior and sorted conflict reporting are unchanged.

On the installed Python 3.14 test environment (128 distributions, 30 reads),
the former full relisting measured 2.54 ms median / 2.94 ms p95; the filtered
scan measured 0.49 / 0.58 ms and returned the same grouping. These are local
measurements, not a universal performance claim. The existing live-sized warm
turn test retains its 1,200 ms budget and skill/catalog walk checks; only the
requirement to use a metadata cache is retired.

Behavioral regressions now live beside the existing integrity tests. Both
adding a conflict and repairing one are tested with an explicitly unchanged
directory timestamp. Restoring the old memo makes both cases fail. Moving the
entry-type check ahead of suffix filtering fails the scan-cost guard. Restored
code passes all 23 integrity checks; the initial focused run also passed the
four skill-root checks, three provider-health checks and live-sized turn check.

All changed production code is fork-owned. No upstream source, harness RPC,
provider policy or Launcher authority is introduced or changed.

The fork landing gate on 2026-10-14 completed 1,035 files in 1,069.5 seconds
with four workers: 12,687 passed, 56 skipped, zero failures or errors. No file
needed a retry, and no cached green result was used. The native two-directory
probe also returned current metadata on all 100 reads after the repair.
