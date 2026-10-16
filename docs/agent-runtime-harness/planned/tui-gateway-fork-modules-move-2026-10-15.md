# Fork modules leave `tui_gateway/` for `agent_runtime/gateway/` (design)

Status: PLAN — written 2026-10-15; owner approval owed. Row: fork-hygiene-queue,
"Move the shared-provider slice's upstream edits behind fork seams …
`tui_gateway/compute_model_selection.py`". Owner ruling 2026-10-15: no new
package name; the fork `tui_gateway` files move under `agent_runtime/gateway/`.

## In plain English

Upstream owns the `tui_gateway/` folder. The fork has added its own files there,
so every upstream merge has to carry them as extra footprint. The owner chose
the new home. Two things make it more than a rename: `agent_runtime/` checks
that every module declares its layer (none of these do yet), and a few of these
files are reached from upstream files through one-line seams that must be
re-pointed in the same move.

## Evidence (tree at `origin/main` 428e2b0dd09)

- **16 fork-only files** (absent from `upstream/main`), not 14:
  `answer_receipts` (37 lines), `compute_model_selection` (32),
  `contract_catalog` (163), `contract_catalog_data` (274), `contract_seam` (61),
  `contracts/recovery` (106), `execution_result` (14), `inflight_recovery` (40),
  `methods_pdf` (122), `methods_start_chat` (64), `recovery_history` (69),
  `recovery_history_delivery` (95), `session_execution` (168),
  `session_recovery` (66), `session_retirement` (61), `start_chat` (92).
- Importer counts (files naming each): `session_execution` 15, `contract_seam`
  13, the rest 1–4.
- Upstream seam sites that name them: `tui_gateway/server.py` (imports
  `methods_start_chat`, l.3714–3728), `tui_gateway/contracts/__init__.py`
  (registers `recovery`, l.18), `compute_host.py` / `methods_config_set.py`
  (`compute_model_selection`), plus the carried lines listed per file in
  `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`.
  `agent_runtime/gateway_extensions.py` already imports `methods_pdf` by
  optional import.
- Layer gate: `__layer__` per module, `tests/tooling/test_fork_import_layers.py`,
  `tests/fixtures/import_layers_grandfathered.json` (`"undeclared": []` must
  stay empty); method and vocabulary in
  `docs/agent-runtime-harness/planned/god-file-layout-sheets/layers-undeclared-2026-09-25.md`.

## Target shape

`agent_runtime/gateway/` (package, `__init__.py` declared `wiring`, exports
nothing). Each moved module declares its layer:

| Layer | Modules (proposed; the CHANGE commit computes, not guesses) |
| --- | --- |
| models | `execution_result`, `answer_receipts`, `contract_catalog_data`, `contract_seam` |
| policy | `compute_model_selection`, `contract_catalog`, `inflight_recovery` |
| stores | `recovery_history`, `session_retirement` |
| lanes | `session_execution`, `session_recovery`, `recovery_history_delivery`, `start_chat` |
| wiring | `methods_pdf`, `methods_start_chat` |

Upstream files keep exactly one import line per seam, now
`from agent_runtime.gateway import …`; no re-export shims left in `tui_gateway/`.

## Owner decisions (recommendation first)

1. **`contracts/recovery.py`.** Recommend it moves too, and upstream's
   `contracts/__init__.py` keeps its one carried line pointing at the new path
   (the generated-contract test reads the registry, not the folder). If that
   test proves folder-bound, leave this one file in place and record why.
2. **Shims.** Recommend none: every importer is re-pointed in the MOVE commit;
   a shim would be a second door and keep the footprint.
3. **Timing.** Recommend after the current wave lands (the verdict's call) and
   before the next upstream merge, so that merge sees the smaller footprint.

## Slices (build order)

- **S1 — CHANGE: declare layers in place** (still under `tui_gateway/`, which
  the layer gate does not scan, so first add the 16 paths to the gate's scope
  list). Fix any upward edge the gate reports by the three classes of the
  layers sheet. Killing mutation: declare `session_execution` as `models` →
  the gate reds naming its upward import; record it.
- **S2 — MOVE: one commit, `git mv` only plus import re-points**, including the
  four upstream seam lines. Proof: `git diff -M --stat` shows 16 renames at
  ≥90% similarity; `tests/tui_gateway/` and `tests/agent_runtime/` green;
  generated-contract test green.
- **S3 — footprint:** re-run the footprint census, update the ledger rows for
  the touched upstream files; `[up-fp]` must not rise. Killing mutation: leave a
  stale `tui_gateway.session_execution` import in one test → the full-tree
  import scan reds.
- **S4 — tombstone the old paths** in the tombstone registry so a re-created
  `tui_gateway/<name>.py` reds. Reintroduce one → red → revert.

## Blast radius

16 moved files, ~60 importers (fork code and tests), 4 upstream seam lines (no
new upstream lines), the layer fixture, the footprint ledger. No behaviour
change; RPC method names unchanged.

## What it retires

Sixteen fork files inside upstream's tree, the owner's 2026-09-29 flag on
`compute_model_selection.py`, and "carry one more file" on every upstream merge.
