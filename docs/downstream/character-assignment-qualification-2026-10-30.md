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
