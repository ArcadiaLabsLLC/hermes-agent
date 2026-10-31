# Shared character assignment

Character assignment belongs to the existing agent identity. `PersonaInstance`
owns an instance override; `AgentPersona` owns the inherited default. A
config-defined persona stays config-defined. Choosing a character must not
materialize its entire definition and freeze unrelated configuration defaults.
Instance IDs, persona links, placement IDs, chat roots, execution state and
profile settings retain their existing owners.

## Record and command contract

The optional `character_assignment` field is a versioned object on the existing
record, not a new store. Absence means the legacy migration has not completed.
Version 1 contains `revision`, `mode`, `asset_reference`, `operation_id` and
`migration_receipt`. Modes are `inherit`, `unassigned` and `assigned`.
`inherit` is instance-only and follows the persona live. Only `assigned`
carries an asset reference: the existing bare Petdex slug or `chara:<id>`.
The field identifies artwork, not its renderer or the instance's activity.

New local instances of a persona with a migrated character default start with
an explicit `inherit` record. Existing unmigrated siblings keep their legacy
choices until reconciled; creating a new sibling never cuts those over.

The runtime advertises four methods independently in the existing RPC manifest:

| Method | Tier | Result |
| --- | --- | --- |
| `runtime.character.assignment.get` | read | Exact subject, assignment and revision; zero means unmigrated. |
| `runtime.character.assignment.preview_migration` | read | The same read, original sources and their fingerprint. |
| `runtime.character.assignment.migrate` | console | Activate an unambiguous inventory, retaining a versioned receipt. |
| `runtime.character.assignment.set` | console | Save an explicit choice against the revision the editor read. |

Every request identifies `kind` (`instance` or `persona`), `id` and
`persona_id`. Instance requests must match both stored IDs exactly. Runtime and
account routing belong to the existing authenticated connection and store root;
no caller-selected filesystem root is accepted.

Writes require `expected_revision` and `operation_id`. The first write also
requires the preview's `source_fingerprint` and the same `local_sources`
inventory (`scope`, `value` pairs). A changed inventory or revision refuses the
write. Repeating the last operation with the same choice returns its durable
record; reusing that operation ID for a different choice refuses. Repeating
migration never restores an old choice over a later edit. A successful reply
contains the exact subject, saved record and acknowledged revision.

The existing stores serialize record writes. Unrelated saves retain the stored
character field, including a stale chat-turn copy loaded before migration.
Character-only edits reload the other fields under the same lock. Realm sync
uses the existing three-way merge and store adoption, with a checked local
character baseline. Missing data from an older peer cannot relinquish existing
record ownership. Unknown record versions remain stored and render unavailable.

## Migration and compatibility

`character_assignment_migration.migrate_authored_character_assignments` runs
through the existing plugin startup. It scans the office once while holding
the affected legacy assignment fences, then migrates only exact-instance
placements whose explicit choices all agree. Original office bytes remain
intact. Each record carries its source inventory and versioned migration
receipt. Subsequent starts skip migrated records.

Conflicting placements, inherited placements, malformed references and missing
instance bindings are retained. The client legacy maps have no reliable
account/runtime provenance; a startup scan cannot invent that ownership. These
subjects keep their existing appearance until an explicit character selection
reconciles them. A profile's custom portrait remains an intentional override
and is never rewritten by this migration.

The lock order is legacy character fence, office lock, then agent-record leaf
lock. Startup takes pending subject fences in sorted order. Neither the leaf
write nor its lock acquires an office or chat lock. Events are emitted after
the leaf write completes.

After activation, old office character fields are read-only migration history.
An old client may move the original placement unchanged; changing its character
through that old command receives `character_assignment_migrated`. New clients
read the record in office, profile and chat and use the acknowledged character
command. An older runtime without this capability keeps the existing writer
for unmigrated subjects. A transport fault or an unconfirmed write never selects
that fallback. Offline saves fail visibly and leave the current character intact;
an uncertain response asks the user to refresh before retrying.

An old runtime binary is not a supported writer of migrated records: its older
codec discards unknown fields. Do not downgrade a migrated store in place or
claim the legacy codec can preserve an explicit clear. The retained source data
is evidence for reconciliation, not a second writable assignment authority.
Explicit reconciliation and compensating rollback use the review and restore
commands below. Neither silently selects from conflicting legacy choices.

### Recovery qualification (2026-10-31)

The explicit `set` command can reconcile an inherited or conflicting legacy
inventory after review, including an instance choice of `inherit`. Its receipt
retains the original inventory and fingerprint; changing the persona default
then changes that instance's effective character without editing its record.
An existing unmigrated sibling keeps its legacy authority. A custom profile
portrait remains an override, not evidence of a matching character/model.

`tests/agent_runtime/test_character_assignment_recovery.py` qualifies these
choices and a **quiescent, record-aware recovery** using isolated stores:

- Capture acknowledged persona/instance records, receipts, office history and
  the applicable profile homes together after stopping their writers.
- Restore that same checkpoint with a runtime/client pair that understands
  version 1 assignments. Reopen the records and verify the exact subject,
  inherited/cleared/assigned choice, profile bytes and revision before writes.
- Repeated acknowledged operations remain idempotent, stale editors still
  refuse, startup does not replay migration, and legacy placement commands can
  move actors but cannot change their character.

This is recovery of the captured generation, not permission to discard later
edits or to run an old binary against migrated data. Rolling back to a
pre-migration backup loses subsequent choices. No automated live-store restore,
old-schema downgrade or mass reconciliation was added. Such downgrade remains
outside the qualified path. The Shared character review described below gives
retained conflicts and persona defaults an explicit choice through their existing
owner; custom portraits remain independent overrides.

## Validation

Behavior is exercised by `tests/agent_runtime/test_character_assignment_records.py`
and `tests/agent_runtime/test_character_assignment_migration.py`, alongside the
existing persona, instance, realm-sync, office and state-patch suites. Client
qualification and rollout evidence live in the client plan; this document owns
the runtime field and RPC contract.

The [qualification record](../downstream/character-assignment-qualification-2026-10-30.md)
separates completed checks, repaired regressions and unrelated baseline failures.


### Explicit review and compensating rollback (2026-10-31)

The client profile's Shared character review consumes `preview_migration` for
an exact instance or its persona default. A first save submits the inventory
fingerprint actually shown to the user; changed inventories and revisions
refuse. Inherit, explicitly unassigned and assigned remain distinct. Choosing a
persona default affects only its inheriting record-owned instances; explicit
and unmigrated siblings retain their choices. Custom portrait bytes stay under
the existing profile-avatar owner, as independent overrides. Review never
asserts that a portrait depicts the selected character.

`runtime.character.assignment.restore_previous` (console tier) accepts the same
exact subject, expected revision and operation ID. It restores the immediately
previous **record-owned choice** as a new revision inside the existing store
lock. The version-1 assignment carries additive `previous_choice` (mode, asset,
revision) and `operation_kind` fields. No second history store or writer exists.
Receipts and unrelated settings are retained; duplicate restore operations are
idempotent and stale restores refuse. Inheritance is restored as a live link,
not a copy of the persona's former character. The first migration cannot restore
ambiguous legacy authority; it must be explicitly reconciled instead.

This is the supported appearance rollback paired with the record-aware recovery
procedure above. Rollback of deployment must retain a version-1-capable runtime
and client; removing the review UI does not remove record ownership. In-place
old-binary/schema downgrade remains unsupported. No live user inventory is mass
reconciled by installing this change.
