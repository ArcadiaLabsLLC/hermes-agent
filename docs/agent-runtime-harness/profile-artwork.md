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
