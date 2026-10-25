# Test-child Python spawn cost — 2026-10-24

Row `FH-TEST-CHILD-PYTHON-SPAWN-COST` (fork-hygiene queue): a `sys.executable scripts/check` child
measured 6–9 s under the fork runner (lane w1022a-tests junit, 2026-10-22) against ~1 s outside it, and
the row asked for a measurement of child start-up inside vs outside the runner before any more per-test
bounds are raised.

## Measurement (lane w1024t-hermes, 2026-10-24, best of 3, same box, other lanes live)

| where | `scripts/check --help` | `scripts/check --only bogus` |
|---|---|---|
| outside the runner (plain venv python) | 0.56 s | 1.01 s |
| inside the runner, full inherited env (a probe test via `scripts/run_tests.sh`) | 0.92 s | 0.71 s |
| inside, minus one runner variable at a time (`HERMES_HOME`, `HERMES_GATEWAY_LOCK_DIR`, `HERMES_REGISTRY_WRITE_FENCE`, `HERMES_TEST_CHILD_STARTUP`, …) | — | 0.56–1.09 s |

The runner's environment, temp root and guards add nothing measurable: a child costs the same ~1 s
inside and outside. The 6–9 s figures were taken with the box saturated (the same day's tooling runs hit
per-file timeouts on whole-tree walks for the same reason).

## Decisions (ruled 2026-10-24, owner standing instruction "go with recommendations")

1. **Raise no per-test bound for child start-up.** Recommendation taken: the cost is box contention,
   not the runner; a bound raised for a loaded box hides a real regression on an idle one.
2. **Judge a slow child file on an idle box only** (the existing perf-phase rule): a junit time from a
   saturated run is not evidence for a bound.

Nothing to build; the row closes REFUTED with this note as its record.
