# R011 resident and writer completion — 2026-10-07

Frozen dependency boundary: `6e2c7047980b9105138b8d042b481dbcaa151897`, branch `fix/resident-writer-lifetime-20261007`. Main base `f1d285e4faf09aec1e6b973e307c439201248d0c`; reviewed anchor `efad97d0952081213f2f352b967d333a8011f278` and QA parity `d30264b544fa19fc7a43aea52d5c28e1d7da3856`. Only queue conflict joined independently reviewed completed R041 and promoted-brief removals; all current evidence and other ownership preserved.

All six steps in [writer checkpoint](runtime-writer-checkpoint-2026-10-07.md) are implemented. The preserved original WIP patch remains outside the old runtime tree unchanged. Product implementation is fork-owned; no upstream edits, private actor rebinding, registry refcount mutation, global TTL cache or assumed serve owner.

## Ownership

- `ChatSessionWriterOwner` owns each command/prewarm's canonical resolved scope until finally. One acquisition per path per request. Bare callers outside these boundaries retain their existing ownership policy.
- `ChatSessionWriterLease.resident_pin` performs public `hermes_state_registry.acquire(scope.db_path)` and requires acquired object **is** the constructor writer. A successor mismatch releases that successor and refuses before factory/publication; failed preparation or factory releases exactly once.
- `AgentRunExecution` publishes `OwnedResidentActor(actor, writer_lease)` to the fork resident registry. The constructor uses its existing writer parameter; production never inspects or mutates an actor's private DB/compressor fields. Actual constructor-generation identity is an independent reuse prerequisite; a mismatch reports `resident_rebuild_writer_generation_changed` and rebuilds.
- The resident owns its pin until retirement. `_close_entry` closes the actor then releases its lease in finally. Signature, revision, active tip, generation, TTL, LRU, explicit eviction, registry close, reset/disable and construction/publication failures are covered. Registry close drains every pin even if one actor close raises KeyboardInterrupt. Configuration replacement is serialized and closes the prior registry before publication; closed registries refuse acquisition.
- Deferred finalization transfers the turn reference only after turn borrowers finish. Cancel/run and rejected thread constructor/start paths release or retain the actual generation according to the executing owner. Resident retirement never releases another turn or tail's reference.
- Prewarm owns its complete prepare/construct request boundary. Refusal/failure/yield before publication releases the request writer. Yield after publication leaves the resident pin alive; its next turn can reuse. Scheduling carries only root/instance and acquires no writer before execution. No registry means no prewarm writer.

## Measured outcome

| R011 cost | Before | After and scope |
| --- | --- | --- |
| 256 instance rows, two preparation evaluations | 512 JSON reads | 256 reads + 3 fresh directory fingerprints; authoritative admission/commit still fresh |
| 186 warm skill manifests, two preparation evaluations | 372 stats | 186 stats; next request and tool authorization remain fresh |
| Three overlapping writer requests | 3 physical opens | 1 physical open, 3 independently owned request references, final live 0 |
| Two serial turns with actual resident owner | per-turn bare opens | 1 physical open; final close on resident retirement |

Read epochs were reviewed in dependency `39964eb11f1470c7d16bcf8c03a56289c2189efc`; see [read acceptance](runtime-read-epochs-2026-10-07.md). Writer census is repeated on real temporary SQLite databases. Serial reuse requires the existing resident feature to be enabled; without a resident, serial request writers close/reopen. Counts are operation savings, not an end-to-end latency guarantee. File-generation transition simulates the OS identity probe while both handles are real SQLite writers; no live Windows file-unlink claim.

## Focused acceptance

Initial two named writer files: 41 green. Integration: 63 green, selecting new resident file, tail/title/identity files and seven exact registry/prewarm nodes. Restored two writer files after controls and added concurrent turn/tail test: 46 green, including printed overlapping/serial census. Final interrupted-close/reset/retirement nodes: 12 green. Added yield-after-pin case: 1 green. Batches overlap; do not add as unique suite coverage. Ten touched Python files Ruff green; final two modified files Ruff green again.

New resident-pin omission and generation-comparison omission each produce 1 expected red, then exact source bytes are restored. Historical turn factory/release/tail controls remain recorded in the preserved checkpoint. Actual ProfileAgentRunner prewarm followed by run keeps the same constructor writer; real temp-DB proof covers different roots/heads, concurrent turn+tail+resident ownership, close exceptions, every retirement path, pin mismatch, factory/publication failure and old-generation tail completion. Provider transport is deterministic; no real model call is claimed.

Raw logs in coordinator outputs: `resident-writer-focused.log`, `resident-writer-integration.log`, `resident-writer-restored.log`, `resident-writer-close-final.log`, `resident-writer-pinned-yield.log`, `resident-writer-{pin,generation}-red.log`; controls `resident-writer-controls.py`. All-worktree dirt inventory `resident-writer-worktree-inventory.json`. Original QA WIP and Job2 trees preserved.

Queue delta removes only R011 after all three costs have a bounded measured owner. Ready for parent batch review; Claude owns full validation and user owns landing. No full suite, broad selection, root analyzer or main product landing.
