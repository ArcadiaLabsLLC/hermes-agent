# Transcript delivery and recovery repair — 2026-10-14

The existing steer buffer now preserves the distinction between operator input
and background notifications. Addressed input carries its client id and its
position from the existing protocol emitter through native persistence. There
is no second input queue or transcript store. Operator history exposes the
journal's terminal outcome. The existing turn-resolution verb can acknowledge
an interrupted turn without deleting its terminal evidence.

Persona identity, prompt composition, permissions, tools, memory, ownership and
delegation are unchanged. This repair does not require agents to narrate every
steer. Delivery after the final tool drain is a separate audit row: this slice
proves inputs consumed by the active turn, not a new next-turn scheduler.

## Boundaries

- `agent/steering.py` carries typed inputs in upstream's existing string-compatible
  buffer. Three upstream integration seams use it; footprint ledger entries name
  their native value and hold any upstream submission for review.
- Plain-text append callers retain their existing ordering. Requeued typed
  batches precede inputs that arrived while the batch was drained.
- Display text is captured alongside addressed input at admission, not recovered
  by importing a private upstream compression parser.
- `TurnResolution` selects the existing journal mutation. Dismissal keeps the
  state `interrupted`; the projected terminal marker still settles old tools.
  The client hides the acknowledged card. Missing-prompt markers say so.

## Verification

The initial full fork gate selected 1,115 files: 15,031 passed, four failed,
one setup error and 53 skipped. Its failures led to four corrections: retain
plain-text requeue behavior, address the retry test by marker kind now that
operator rows also carry outcomes, regenerate the CLI reference, and remove
the private upstream import. The five-file focused rerun passed all 47 tests.
The package-manager setup error reproduced on unchanged base `0525cc6c37`:
the shared Python 3.13 interpreter cannot build a fixture requiring 3.14. It is
filed in the fork-hygiene queue and is not a transcript regression.

The provenance suite exercises the real inbox, protocol emitter, SQLite flush
and reopened history. Recovery tests cover exact owner/root/client/turn guards,
idempotent dismissal, terminal-tool settlement, failure history and absent
prompts. Existing upstream steering and compression tests remain intact.

Recorded before implementation: the recovery suite had five failing cases;
the provenance suite failed the user-wrapper, coalesced-input and overwritten-id
checks. Commit `30c0cd3c50` records those red results. Follow-up checks and the
final gate receipt are recorded in the landing commit.

The second whole-tree selection ran 1,115 files (81 cached greens, 25 clean
cache-audit samples): 14,236 passed, one failed, one setup error and 51 skipped.
Its routing-ladder failure was in the new input row builder. The builder now
chooses user/notification shape once, then attaches shared metadata. The focused
recovery, provenance and routing checks passed all 25 tests after that correction.

Independent review also found that the canonical projection dropped a system
notification's recorded identity. It now carries that identity without inventing
an anchor. The inbox/SQLite test compares raw and canonical ordering; removing
the system identity carry made it fail at the notification's position. No
persona or operator-policy authority moved.
