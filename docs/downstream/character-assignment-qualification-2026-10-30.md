# Character assignment migration qualification

The owner approved migration onto the existing agent record, preserving persona
inheritance, characters, settings and the instance system. The field and command
authority is [Shared character assignment](../agent-runtime-harness/character-assignment.md).
Client qualification lives in
`EterniaLauncher/docs/spatial/CHARACTER_IDENTITY_3D_PILOT_PLAN_2026-10-30.md`.

## Scope and limits

The migration keeps the existing persona and instance identities, store roots,
realm contracts and event stream. Explicit, agreeing exact-instance placements
can migrate automatically. Ambiguous legacy defaults and custom portrait
relationships are retained for reconciliation. This is P1b's record contract
and conservative cutover, not full rollback qualification or the real-model pilot.
An older runtime binary cannot safely write a migrated store in place.

## Regression evidence

The required fork landing gate ran over 1,366 files. Its initial result was
15,411 passed, 46 failed, seven errors and 64 skipped; it was not a clean run.
The migration's integration failures were repaired: fixtures now use actual
persona/instance contracts, generated RPC and stream fixtures include the
additive field and methods, and the existing corrupt-row repair door remains
the only path permitted to replace unreadable instance JSON. New production
modules were staged before the tracked-file packaging test.

The 14-file integration follow-up passed 254 checks with eight failures confined
to the unchanged pre-push script test harness. The restored character and office
tests separately passed 92 checks. The native conversation and chat-head repair
set passed 58 checks across six files, including three actual provider turns.

Two baseline failures required by the changed-symbol checks were repaired here:

- `test_chat_head_per_profile_writers.py` compared native Windows path strings
  with POSIX allowlist keys. Both sides now use the existing POSIX vocabulary;
  the forbidden-writer assertion is unchanged.
- `recorded_instance_chat_head` previously found only the selected chat binding.
  It now uses the existing exact minted-session owner before the legacy binding,
  allowing another conversation of that instance to read its own profile store
  without selecting that conversation or minting another identity.

Both original failures were reproduced independently on the candidate and base
`92c21c580f` by the canonical `--confirm-red` command before repair.

Three other files were rerun on clean main `19e49b3c57`: two supervisor fixture
identity assertions and 12 pre-push harness assertions still failed. They are
recorded in `RT-WINDOWS-SUPERVISION-FIXTURE-IDENTITY` and
`FH-WINDOWS-PREPUSH-SHELL`. The other pre-existing Windows failures remain in
`RT-WINDOWS-BASELINE-REGRESSIONS`. No failing file was removed or skip-listed.

## Red-first guarantees

Each mutation below produced assertion failures with exit 1 and was restored.
No baseline, severity rule or assertion was relaxed to turn it green.

| Mutation | Observed failure |
| --- | --- |
| Remove stored-record preservation during an unrelated save | A stale draft overwrote the character choice. |
| Remove assignment revision comparison | Concurrent/stale choices were accepted. |
| Resolve inheritance from the instance instead of the current persona | Persona updates failed to propagate. |
| Accept divergent legacy sources | Conflicting placements migrated silently. |
| Ignore the migration inventory fingerprint | A stale preview activated ownership. |
| Disable the old office character fence | An old client changed a migrated character. |
| Disable inheritance initialization for new instances | A new sibling lacked its inherited record. |
| Author an office before the workspace/identity fences | Both existing no-office-on-refusal assertions failed. |
| Remove the RPC subject-kind type guard | Malformed input returned `handler_failed` instead of the typed refusal. |

The config-persona stale-draft regression was also observed red before repair:
an ordinary save materialized a persona with no assignment after a character-only
config migration. Its test retains the assignment and still permits the intended
name edit. This is distinct from the existing stored-persona stale-save case.

## Final acceptance

On the final production tree, `scripts/prepush.sh` completed with exit 0:
**108 queue/text checks across nine files**, the doc-citation check, and
**3,123 checks across 193 files** covering every test that references the changed
shared symbols plus touched tests and the required name/dispatch censuses.
There were zero failures and three existing skips. Wall time was 258.9 seconds
with eight workers; this is a correctness result, not a performance benchmark.
Ruff also passed over every changed and added Python file.

The dispatch census initially identified string comparisons against the newly
declared mode vocabulary. Mode behavior now belongs to one explicit policy
table; no census baseline was expanded. Disabling inheritance in that final
table again produced assertion failures, then the table was restored before
the accepted run. The ordinary config-persona save fix is included in that run.

The wider initial gate remains recorded above with its failures. The completed
changed-symbol, integration-repair and per-file results qualify this migration;
they do not reclassify unrelated baseline failures as a clean whole-fork run.

## Reviewed reconciliation and recovery checks — 2026-10-31

The follow-up adds four behavioral checks in
`tests/agent_runtime/test_character_assignment_recovery.py`. They exercise the
existing command and store owners; no assignment writer, default, live store or
record codec changes. The reviewed inherited choice keeps its inventory receipt
and follows later persona changes while an unmigrated sibling remains untouched.
Quiescent recovery checks all three durable modes, exact IDs, existing settings,
custom portrait bytes through the existing avatar RPC, retry acknowledgement,
stale revision rejection, startup idempotence and the legacy placement fence.

The new file plus the existing record, migration and avatar RPC files completed
with **36 passing tests across four files**, exit 0. The new tests failed with
assertion errors when live inheritance was disabled (two failures), and when
the legacy character fence was bypassed (three failures). Both production
mutations were restored byte-for-byte. The queue/text, citation and touched-test
prepush checks also completed with exit 0 before the dependency-row landing.

The supported recovery boundary is documented in
`docs/agent-runtime-harness/character-assignment.md`. This evidence does not
qualify an old-runtime downgrade or reconcile actual conflicting user artwork.
At that checkpoint the rollout row remained open for explicit review and recovery
product support. The following P1c acceptance closes that independent implementation
scope; actual user conflicts remain retained until explicitly reviewed.


## P1c / P2d acceptance — 2026-10-31

Candidate `65e05b4c62` extends the existing settlement outbox and record writer.
Successful and refused terminal payloads retain their validated exact persona and
instance owner through disk reload, retry and ACK. No owner is borrowed from a
persona default or a current selection. A real sandboxed successful provider turn
was also captured by the existing client fixture generator from integrated
candidate `2791bf79b0`; it emitted both owner fields.

The existing assignment writer now retains the previous distinct record choice.
`runtime.character.assignment.restore_previous` uses that same store and CAS,
retains the original migration receipt, and writes a new revision. Idempotent
retries, stale drafts, unchanged saves and live inheritance have direct coverage.
It refuses to restore first migration into ambiguous legacy authority. Ordinary
profile settings and realm/instance identity retain their existing owners.
The client supplies explicit instance/persona review and preserves custom portrait
overrides without inventing an artwork relationship. No live user inventory was
mass-reconciled or replaced. Old-binary in-place downgrade remains unsupported;
record-aware compensating edits and the prior quiescent recovery qualification
are the supported rollback boundary.

### Validation

- Final changed-symbol consumers and the two required name/dispatch censuses:
  **213 passing checks across 11 files**, zero failures. Queue/text checks and
  citation checks also completed with exit 0 through `scripts/prepush.sh`.
  Ruff passed on the changed Python files.
- Dropping the owner at `record_settle` made both exact-owner tests fail.
  Bypassing the revision comparison made all three restore-mode tests fail.
  Both production mutations were restored byte-for-byte before the accepted run.
- The initial wider fork gate was **not clean**: 1,378 files, 15,548 passing tests,
  30 failures, zero errors and 66 skips. Six failures in three RPC-manifest tests
  were this slice's additive-method expectation and were corrected by regenerating
  the manifest from its producer. All three files then passed alone.
- Unrelated failures were compared one file at a time with `origin/main`, using
  the canonical `--confirm-red` command. Existing phone, supervision, turn-cost,
  work-brain and prepush-shell failures retain their original queue owners.
  Additional absent-flag, project root-observability, writing-command skeleton,
  child-collection, legibility and generated-tree findings were filed separately.
  They are not fixed, suppressed or reclassified by this character change.
- A scheduler config test was unstable: its initial bundle failed then passed
  alone, a later isolated comparison failed only on candidate, and a subsequent
  isolated candidate passed without a production repair. Its qualification is
  tracked as `FH-SCHEDULER-CONFIG-TEST-STABILITY`; this is not a clean-suite claim.

The model renderer and Aura publication remain separate client-owned stages.
No renderer claim, model asset, instance system or assignment store was replaced.

Final isolated classification completed: all eleven remaining failing files
reproduced the same failing node IDs on unmodified bases `ce6a7188ed` or
`bf6a9a3890` (the latter adds queue records only). The child-job file passed alone;
the three RPC-manifest files passed after the producer-generated expectation fix.
All fifteen canonical comparisons completed; none was accepted from a timeout or
incomplete process. The separate scheduler instability remains recorded above.
