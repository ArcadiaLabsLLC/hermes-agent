# Runtime Wave1 checkpoint — R011 / R039

Frozen dependency: prior runtime fc1edc5341a017b2ef2b9dc84189d0e3b3c6df5e; origin/main 8a5c19d4125a1460f1d8ecd67ef67177d468c0a2; conflict-free integration d4b5a3952ecfa0345dfcbcaa6064a0439b1012a0. Queue union preserved. No main write. Job2 tree untouched; original QA patch and evidence retained.

## R039 — DONE (focused proof, awaiting batch review)

Both native conversation and snapshot workers report the executing interpreter's PID and creation time before ready/handshake completes. Parent validates that tuple against the identity-fenced owned spawn tree. NativePeer.process_identity is the verified interpreter tuple; launcher_identity and containment remain the spawn root. Separate ledger purposes register native-conversation-launcher / native-conversation and snapshot launcher / worker. After receipt, execution_possible uses interpreter creation-time/liveness independently of a launcher exit; before receipt it uses the launcher's poll.

observe_process_tree counts root plus recursive descendants, checking creation time around memory reads. Complete observations return aggregate RSS; partial, gone, reused or unavailable observations never invent a zero aggregate. Startup diagnostic exposes execution/launcher PID, owned process count, RSS and completeness. This does not add continuous RSS polling or change containment ownership.

Proof: 11 tests passed in runtime-wave1-identity-final.log (new identity file, existing native boot file, two explicit snapshot nodes). After parent found the launcher-exit gap: 9 identity tests plus 3 census probes passed in runtime-wave1-checkpoint.log. The native boot test checks actual interpreter ledger registration. Selected real Windows venv probe observes launcher plus interpreter separately and confirms tree identity. Named Ruff analysis of 10 changed files passes.

Three controls each fail the exact expected assertion: restore launcher identity -> (10,1) != (20,2); root-only enumeration -> missing interpreter; restore launcher-poll gate -> still-live interpreter incorrectly reports false. Exact original bytes restored in finally. Evidence logs: runtime-wave1-identity-control.log, runtime-wave1-tree-control.log, runtime-wave1-lifetime-control.log.

## R011 — pending; measured design checkpoint (no cache installed)

Isolated synthetic representative census: 256 persona instances and 186 SKILL.md files, no operator records or credentials. This measures owners independently, not end-to-end context_built or total turn savings. Source is _runtime_wave1_census.py; log runtime-wave1-checkpoint.log.

| Cost | Observed | Concrete follow-on |
| --- | --- | --- |
| Instance scan | two scans each decode 256 rows; 73.855 / 75.656 ms; next scan detects corruption | Introduce a request-owned InstanceReadEpoch carrying PersonaInstanceScan including unreadable count, scoped to canonical resolved store root. Pass it through roster/admission readers only. Invalidate on every store write/mint/retire and at admission/commit boundaries; keep authoritative uniqueness and commit reads fresh. Never narrow uniqueness to one row or memo across turns. First bounded batch may remove duplicate ensure_for_persona work independently; prove creation, deletion, rename, corruption, two concurrent requests and canonical root isolation. A shared revision does not currently cover external file writes, so no cross-turn scan cache is authorized. |
| SessionDB writer | three WRITE acquisitions produce three distinct objects; 499.060 / 21.618 / 13.163 ms; overlapping public registry acquire returns one object | Add a fork-owned ChatSessionWriterLease resolved by ChatSessionScope and backed by public hermes_state_registry.acquire/release. Declare turn entry/early-refusal/failure finally ownership. Transfer an acquired reference to deferred finalization while its DB users run; release in its finally. Use existing serve-owned registry reference where present; without one, final release closes and serial turns may still reopen. No global writer cache or guessed serve owner. Focused real temp DB tests: overlap/serialization, two roots, early failures, off-path tail, replacement generation, close and no leaked refs. Registry lifetime machinery already exists; integrating the lease is local design work, not an external blocker. |
| Skill frontmatter | cold 186 stats + 186 reads 218.138 ms; warm 186 stats + 0 reads 31.807 ms; edit changes compatibility next read | Add an explicit request-preparation read epoch keyed by canonical candidate path with already obtained file identity/stamp. Resolve/parse each candidate once for that coherent prompt-preparation epoch; discard at request_sent. Pass parsed immutable frontmatter to repeated policy/observability evaluations within it. Keep later tool authorization on fresh reads; preserve per-profile/root and surface/mode policy. Do not substitute the 15-second observability catalog for authority. Prove edits/replacement/deletion between turns, duplicate evaluations within one epoch, denied/corrupt manifests and root isolation. One catalog pass still needs one stat per manifest unless a real revision owner is introduced; do not promise elimination of required external-edit detection. |

The row stays TAKEN and pending. These are three separate implementation-ready slices; missing lifecycle in one does not hide feasible reuse in another. No savings claim and no unsupported cross-turn caching. Census probe is retained as evidence, not added as a performance ratchet to the suite.

## Next bounded review correction

R007 remains pending review correction: in-flight ToolHeartbeat beat can race real finish and emit progress after turn.end. Prior manually joined test is insufficient. Next approved repair: deterministic blocked beat / real finish race; fence progress at emit lock boundary, preserve terminal and end-segment frames, no blocking join/deadlock. Only named test. No R008/R010/R034 or Job2/Job3 expansion.

Full suites and landing gates were not run. Claude owns full validation; user owns landing. Worktree retained.
