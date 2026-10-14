# Reviewed Console Redo

Owner-approved D11: one Redo of the last completed Undo, with the original
chat/files/both scope. It restores saved content, never model execution or
external side effects. A failed or rolled-back Undo does not replace it.

## Owners and boundaries

| Responsibility | Existing owner extended | Boundary |
|---|---|---|
| Lifecycle, receipt, pending fence and partial recovery | `agent_runtime/operator_undo.py` | One typed direction and one transition writer for Undo and Redo; existing status/recover APIs serve both. |
| Last-Undo eligibility and seven-day policy | `agent_runtime/operator_redo.py` | Fork-owned policy, one pointer in SessionDB metadata. No transcript/file copy or client recovery plan. |
| Reactivating chat | `hermes_state_history_controls.py::SessionHistoryControlsMixin` | Exact existing native row IDs; payload digest, active membership, high-water mark, rewind count, native writer guards and transactional receipt. This module is fork-owned. |
| Files | `tools/checkpoint_manager.py` | Review the existing restore receipt's inverse; reuse `restore_preview`, its backup, per-file checks and write primitives. No second file writer or Git store. |
| Expiry cleanup | `tools/checkpoint_maintenance.py` | Existing maintenance releases expired completed-restore pins. Unfinished recovery has no expiry. Receipts remain for idempotency. |

An intervening message, rewind, compaction, archived-content edit or changed
settings refuses Redo. The affected files must still match the completed Undo's
targets, including absence; another agent's authored change is also a conflict.
Unrelated file edits remain untouched. Review and apply both check eligibility.
Partial filesystem writes use the same explicit finish/rollback flow as Undo.
Chat restoration and its receipt commit together only after files succeed.

The seven-day window starts when Undo is accepted. A newer completed Undo
replaces the opportunity. Redo completion releases its source and recovery
pins; failed/partial operations retain the backups needed for recovery. Normal
checkpoint pruning cannot remove leased objects. Expired objects become
reclaimable at the next existing maintenance pass; expiry does not run a timer
or introduce a scheduler.

## Runtime contract

Every call uses the existing exact operator identity and console authorization.

| Method under `runtime.operator.conversation.` | Additional request | Result |
|---|---|---|
| `redo.available` | none | `available`, optional `mode`, `expires_at`, or refusal `reason`; no workspace scan |
| `redo.preview` | none | `preview_token`, original `undo_operation_id`, fixed `mode`, expiry, affected history and reviewed file plan |
| `redo.apply` | `preview_token`, new `operation_id` | Existing Undo result with `direction: redo` |
| `undo.status` / `undo.recover` | unchanged | Same durable result and explicit finish/rollback, for either direction |
| `history.pending` / `history.cancel_unapplied` | unchanged, action may be `redo` | Same discovery and delayed-request cancellation fence |

New refusal reasons: `redo_unavailable`, `redo_expired`. Existing change, busy,
ownership, cancellation and recovery reasons remain authoritative. Clients do
not choose a new mode or file subset when redoing a reviewed Undo.

Launcher adds a quiet **Redo last undo** action to the existing history notice
and a compact review using its current controls. A pending operation survives
review closure. Chat refresh completes before the operation is acknowledged;
Redo preserves the current composer draft. Older runtimes expose no Redo
action. Consumer: `EterniaLauncher/lib/features/agent_console/history_controls/`.

## Upstream evaluation, held for owner review

| Upstream file touched | Native benefit to establish before submission | Disposition |
|---|---|---|
| `tools/checkpoint_manager.py` | A user can reverse an erroneous reviewed restore, including creations/deletions, after pruning or process restart, while protecting later edits. Existing recovery provides the write/rollback mechanics; it lacked a retained, reviewable inverse of a completed operation. | Extend the existing held reviewed-restore candidate. No Eternia identity, RPC or seven-day policy enters the native owner. |
| `tools/checkpoint_maintenance.py` | Completed-restore retention leases must eventually release pins without expiring interrupted recovery. | Dependent on that reviewed/resumable-restore proposal; not a standalone cleanup PR. |

No upstream submission is authorized by this implementation. Before pitching,
check for an upstream issue/discussion and maintainer demand, prove a native
user problem, and show why an existing public primitive cannot deliver it.
Product neutrality alone is insufficient. Fork orchestration stays here.

The installed v0.21.7 pre-commit hook also rejected 13 existing findings in
this touched checkpoint owner, reproduced from unchanged main: twelve typing
annotations and an unused index-path local left by the earlier restore
extraction. These are corrected here without bypassing the hook. The latter
only computed a path; native restore tests qualify its removal. The existing
fork-hygiene row about whole-file hook scope remains open.

## Verification

`tests/agent_runtime/test_operator_redo.py` exercises real RPC, SQLite and Git
snapshots: all modes, exact row identity, lost acknowledgement, interrupted
writes, finish/rollback, intervening edits, pruning/GC, expiry, creation/deletion,
and cancellation. Existing Undo and native reviewed-restore tests remain in the
focused qualification. Final test receipts and killing-control output belong
in the implementation commit, not an untracked claim of evidence.
