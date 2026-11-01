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

The first complete fork landing run reported 9,804 passing tests, 23 failures,
63 skips and no errors across 1,384 files. That run exposed the seed race above;
its isolated portrait retry passed, but did not qualify the race away. A fresh
landing run after the shared-lock repair is required before acceptance.

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
