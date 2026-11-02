# Profile artwork

`agent_runtime/profile_avatar.py` owns bounded reads and atomic replacement of
the existing profile asset. It does not write character assignments, personas,
instances or profile configuration. The profile resolver remains
`profile_context._profile_home_for_token`.

`runtime.profiles.avatar` retains its read-tier contract and extension order:
PNG, JPG, JPEG, WEBP. `runtime.profiles.avatar.set` is a console-tier method,
published in the same runtime manifest. Its parameters are `profile`,
`expected_handle` (a SHA-256 content handle, or explicit null for no portrait),
and `data_base64`.

The upload is one verified, decodable PNG frame, at most 1024 pixels per edge
and 512 KiB. Its base64 envelope fits the existing 1 MiB request limit. The
client prepares a static preview before asking the user to save; source artwork
is never modified. The runtime independently validates every bound.

Under the profile's artwork lock, the writer compares the current content
handle, then uses the existing atomic byte writer to replace `assets/avatar.png`.
Other avatar formats remain untouched as historical assets. A stale revision
returns `stale_avatar`; unreadable existing artwork fails closed. Identical
content returns the same acknowledgement without rewriting it. Success uses
the read contract's profile, media type, bytes and content handle, so readers
can verify both subject and acknowledgement.

The profile must already exist. Traversal tokens, external/symlink write targets,
invalid images and oversized inputs are refused. A missing or lost response
is not success; the client refreshes from the runtime before another attempt.
There is no argv, filesystem or second-store write fallback in Eternia.

Artwork belongs to the runtime profile: agents using that profile share it.
Character selection still belongs to the existing persona/instance assignment
contract. Changing one does not migrate, clear or overwrite the other.

## Exact-agent appearance

`runtime.character.appearance.set` adds a portrait choice to the existing
instance character-assignment transaction. It takes the same exact instance,
persona, expected revision, operation id and migration receipt as character
selection, plus `portrait: {mode: character}` or
`portrait: {mode: custom, data_base64: ...}`. It never accepts persona scope.
Character and portrait commit in one row write and acknowledgement; a stale
revision commits neither. Ordinary character commands retain the portrait.

The optional `portrait` field on that record stores a mode and, for custom
artwork, its profile token and SHA-256 handle. Bytes are immutable assets under
`assets/portraits/<digest>.png`, validated with the existing upload limits.
Preparing an asset does not select it. A refused save can leave an unreferenced
asset, but cannot replace another agent's portrait. No image bytes enter the
runtime snapshot. `runtime.character.portrait` resolves the exact instance and
returns only its referenced bytes, checked against the content identity.

An absent portrait choice preserves the previous shared-profile precedence.
It is not silently migrated or relabelled as agent-owned. Explicit `character`
uses the resolved character's still; explicit `custom` affects only that agent.
Neither changes the character's persona inheritance, instructions or settings.
An older peer cannot discard existing portrait ownership during adoption.

Referenced assets travel through the existing profile-file realm publisher
and merge owner. Only digest-named, bounded PNGs are admitted; changed bytes
under an existing identity are refused. Missing assets are reported as
unavailable and retain the character fallback, never another agent's art.
Shared `assets/avatar.*` files remain untouched and are never copied into an
agent override without an explicit choice.

## Windows first-save contention

The initial concurrent-write qualification exposed an existing lock-initialization
race: a second opener could seed the Windows lock byte after its peer acquired it,
and `_prepare.flush` raised `EACCES` outside the retry protocol. The shared
`agent_runtime/locks.py` now prepares inside the same bounded acquisition loop,
using an unbuffered handle so a refused seed cannot remain queued for close.
There is no extra portrait mutex or lock authority.

Both seed-retry and deadline assertions were killed by moving preparation back
outside that loop. After restoration, all 22 lock/portrait checks passed and
100 independent pairs of concurrent portrait writers each produced one save and
one stale-revision refusal. The original failing bundle and its isolated retry
are retained as diagnostic evidence, not reported as a clean first pass.

## Qualification boundaries

The completed fork landing run after the shared-lock repair reported 15,236
passing tests, 23 failures, 66 skips and no errors across 1,384 files. All 15
portrait tests and all seven shared-lock tests passed inside their original
bundles. The 25 sampled cache hits were audited clean. The earlier 9,804-pass run
exposed the seed race; its isolated retry was diagnostic, not acceptance.

One unrelated runner test, `tests/scripts/test_run_tests_tmp_root.py`, failed
inside its bundle while collecting a disappearing Flutter temporary directory,
then passed alone. The canonical one-file confirmation returned `load` with
HEAD green alone. That retained first-attempt failure is covered by
`FH-CHILD-JOB-COLLECTION-ROOT`; the final counts do not claim a clean first pass.

Each of the eight final red files was then run alone on the candidate and on
unchanged base `f6ac4265f4`, using the same Python 3.14 test environment. Seven
files reproduced exactly the same 22 failing node IDs on both revisions:

- Embedded phone session: two nodes (`RT-WINDOWS-BASELINE-REGRESSIONS`).
- Supervised relaunch and connection-drop fixtures: one node each
  (`RT-WINDOWS-SUPERVISION-FIXTURE-IDENTITY`).
- Stream fixture byte/shape checks: four nodes; the missing producer field is
  `core.prompt_observability.chat_contexts[].workspace_context_receipt`
  (`FH-STREAM-WORKSPACE-RECEIPT-GOLDENS`).
- Sessions-export writing positive control: one node
  (`RT-WRITING-COMMAND-HOME-SKELETON`).
- Prepush shell tests: twelve nodes (`FH-WINDOWS-PREPUSH-SHELL`).
- Spatial entry vocabulary census: one node (`FH-LEVEL-ENTRY-VOCABULARY-CENSUS`).

The eighth file, `test_default_brain.py`, initially passed all 21 checks under
direct pytest on both revisions. The canonical runner's hermetic one-file
comparison then reproduced the same failing node on both:
`test_second_machine_with_a_local_brain_moves_its_rows_in`. Its longer Windows
fixture path fails during git worktree creation (`RT-WINDOWS-BASELINE-REGRESSIONS`).
That completed comparison is `pre-existing`, so all 23 gate failures have an
unchanged-base counterpart. They are not claimed fixed. These comparisons
completed with named assertions, not timeouts or collection crashes. The earlier
official comparison wrapper was cancelled while waiting for a slot and supplies
no validation evidence. Existing queue findings and other lanes' claims remain open.

Portrait-specific mutations were killed and restored for the reviewed-handle
comparison, PNG validation, exact subject, atomic write, and preservation of
real persona/instance records. No test ceiling or assertion was weakened.
