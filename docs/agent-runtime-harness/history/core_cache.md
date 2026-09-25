# History — `agent_runtime/core_cache/` (the persisted core's cost and convergence notes)

Rule 7 of the god-file program (`docs/agent-runtime-harness/planned/downstream-god-file-refactor.md` §1) and ruling Q3
(`docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md` §9): narrative that records what a
function used to cost or how it used to behave lives here once the function is rewritten. Lane R3's CHANGE
moved these paragraphs out of `write_back`'s docstring when it became phases; the contract paragraphs stayed.

## `write_back`

From the docstring of `agent_runtime/core_cache/persist.py::write_back`, verbatim.

**Named consequence, AMENDED: a cold store converged in two builds, not
one.** The build is not a pure reader —
``PersonaInstanceStore.ensure_for_personas`` materializes missing instance
rows, and the chat SessionDB is CREATED by the first process that opens it.
On a store where neither had happened yet, the pre-build key described inputs
the build itself then changed, so the next process demoted once and rebuilt.
That was a property of the conservative direction, not a defect. IC-2 closes
exactly that gap for exactly those inputs: the mint and the close are inside
the audited set, so their triples are re-stat'd before the key is persisted
and a cold store now converges on the FIRST build. What is unchanged is the
reason a store may still take two: any input outside the audited set that
moved during the build.

**Cost, named with the rest below, INCLUDING who pays it.** The re-stat is a
second full walk (~300 ms on the operator's live root, less since the
``deleted_archive`` and ``realm_sync/**/.git`` exclusions) on a path that
only runs after a build measured in seconds — 11,235 ms for the cold-boot
re-projection this lane exists to replace. It is skipped entirely when the
caller passed no fingerprint, because that key was already walked after the
build. The part not to discover later: ``build_snapshot`` calls this INSIDE
its coalescing window, so the riders waiting on the leader wait for the walk
too, exactly as they already wait for the megabyte serialize and the fsync
beside it. The trade is ~300 ms once per LED build against a next process
that can be served at all; if receipts show the rider wait matters, the
refinement is to narrow the re-stat to the audited paths (which is all it
reads) rather than to drop it — that loses only the ``foreign_moved=``
observable.

**Cost, named rather than discovered.** EVERY successful default-store build
writes here, and a live-store core is megabytes, so a serve process that
demotes several delta batches in a minute writes that many times. Priced and
accepted for this landing: the write is ~5 ms of serialize plus one fsync
against a build that costs seconds, and the alternative — skipping the write
when the persisted pair would already match — needs the FULL judgement (a
sidecar-only check leaves a tampered core permanently unhealed, because the
read path refuses it while the write path keeps declining to replace it). If
receipts show the churn matters, that is the refinement, gated on
:func:`read_persisted_core`, not a narrowing of which builds write.
