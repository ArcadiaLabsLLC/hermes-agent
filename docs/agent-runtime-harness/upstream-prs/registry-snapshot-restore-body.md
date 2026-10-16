# feat(tools): `ToolRegistry.snapshot()` / `restore(snapshot)` — whole-registry save and restore

Draft PR body (plan `docs/agent-runtime-harness/planned/process-global-state-reset-2026-10-15.md`,
S5). Posted by the owner in a posting sitting; the code and its tests are cut on an `up/` branch
once `tools/registry.py` is outside the upstream-sync fence.

## The problem

`tools.registry.registry` is one process-global `ToolRegistry`. A test that registers a tool (or a
plugin that does so at import) leaves it there for every later test in the same process. The
registry already has the per-name pieces — `snapshot_registration(name, scope=)`,
`deregister(name, scope=)`, `restore_registration(...)` — and the plugin override policy has its
own `snapshot_plugin_override_policy()` / `restore_plugin_override_policy()` pair, but nothing
saves and restores the registry as a whole. So isolation has to be rebuilt per test from those
per-name calls, and each caller has to know every name it might have touched.

In our downstream suite this showed up as hundreds of leaked registrations accumulating across
one bundled process, fixed by moving the affected test into a fresh interpreter — which costs a
process start per test.

## What this PR adds

- `ToolRegistry.snapshot() -> RegistrySnapshot`: under the registry lock, a shallow copy of the
  global tool map, every scoped tool map, the toolset aliases, the plugin override policy, and
  the current generation. Entries are shared, not deep-copied (a `ToolEntry` is not mutated after
  registration).
- `ToolRegistry.restore(snapshot)`: under the lock, replaces those maps with copies of the
  snapshot's and bumps the generation (never rewinds it), so every generation-keyed cache built
  after the snapshot is invalidated rather than served stale; the check-fn cache is invalidated
  too.
- Both are additive: no existing method changes behaviour.

## Tests

- register a throwaway tool after `snapshot()`, `restore()` → the tool is gone from
  `get_all_entries()` and `get_definitions()`.
- replace an existing tool after `snapshot()`, `restore()` → the original handler dispatches.
- scoped registration and a toolset alias are both rolled back.
- `generation` after `restore()` is greater than before it (a cache keyed on the old generation
  misses).
- a snapshot taken, the registry mutated twice, restored twice → idempotent.

## Downstream use

A pytest fixture: `snap = registry.snapshot(); yield; registry.restore(snap)`. Until this lands
the fork's fixture (plan S3) records names before the test and deregisters/restores per name afterwards.
