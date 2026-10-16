# Per-connection tool scope — already answered by D1.03; close with one proof (design)

Status: PLAN — written 2026-10-15; owner approval owed to CLOSE the row after
S1. Row: runtime-queue, "The tool registry's `scope` is keyed by profile home,
so per-connection state (launcher app functions) has no scope: each Launcher
overwrites the shared registry and moves `registry_epoch` on every switch; a
queued turn bound to its sender's link (L5.13) still reads that shared set".

## In plain English

The row describes a real problem as it stood on the morning of 2026-10-10: two
Launchers attached to one serve took turns overwriting the agent's tool list,
and every switch forced a rebuild. Five hours after the row was filed, design
D1.03 landed a fix that did not need a per-connection registry: the registry
now holds **every** attached Launcher's tools at once, and each turn only
*sees* the tools of the Launcher it is bound to. So the redesign the row asks
for is not needed. What is missing is a test proving the one case the row
names — a queued turn — gets its sender's tools, not someone else's.

## Evidence (tree at `origin/main` 428e2b0dd09)

- Row filed `1cac0c3838b` (2026-10-10 14:33); fix landed `0df2a3a79c0`
  (2026-10-10 19:24) "the registry holds the union of every attached
  Launcher's catalog (D1.03 S1)".
- Design: `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md`
  § "D1.03 = L2.24" — option (a), a per-connection registry scope, was
  REJECTED there: `current_scope_key()` is the profile home and threading a
  connection through `get_definitions` is a non-additive upstream seam.
- Code: `agent_runtime/launcher_app_functions.py::_sync_registry_union`
  (l.436; untouched when the union does not change, so a switch moves no
  generation), `_offered_to_bound_link` (l.392, per-entry `check_fn`),
  `_bound_schema` (l.399, per-link schema via `dynamic_schema_overrides`),
  `app_function_tool_scope()` (per-catalog definitions cache key).
- Queued turns: L5.13 FIXED `9204de94eb` + `95d15e6351` — the queued turn binds
  the sender's direct-run link (`serve/queued_turn_origin.py`), so the bound
  link that `check_fn` reads is the sender's.

## Target shape

No new mechanism. The union registry + bound-link visibility is the one
authority; the row closes once its last claim is proven.

## Owner decisions (recommendation first)

1. **Close the row as answered by D1.03** once S1 lands (recommended). The
   per-connection registry the row proposes would duplicate the bound-link
   authority and needs an upstream seam that design D1.03 already declined.
2. **Mutating-tool superset.** The union makes `mutating_app_function_tools`
   a superset across Launchers (blocks more, the safe direction, per D1.03).
   Recommend accepting it; revisit only if an operator reports a wrongly
   blocked tool.

## Slices (build order)

- **S1 — proof test** (`tests/agent_runtime/test_launcher_app_functions_queued_scope.py`):
  two fake links A and B with different catalogs (`a_only`, `b_only`, and a
  shared name with different schemas); a turn queued by B while A is the most
  recent attach; assert the queued turn's tool definitions contain `b_only`
  and B's schema for the shared name, and not `a_only`; assert
  `registry.generation` is unchanged across an A→B→A switch with no catalog
  change. Killing mutations: (a) make `_offered_to_bound_link` return True → the
  queued turn sees `a_only` → red; (b) make the queued turn bind the most recent
  link instead of its origin → red. Positive control: a direct turn on A sees
  `a_only`.
- **S2 — close:** delete the row citing S1's commit and `0df2a3a79c0`.

## Blast radius

One test file. No production change.

## What it retires

A redesign row whose problem is already fixed, and the untested queued-turn
corner of that fix.
