# Conversation approval and speed controls — 2026-10-14

The Console consumes native execution policy through four console-tier RPCs:
`runtime.operator.conversation.controls`, `control.set`, `approvals`, and
`approval.respond` (the latter three share the first method's conversation prefix).
`agent_runtime/operator_session_controls.py` validates the existing install,
workspace, persona, instance, conversation and optional client owner. A setting
write takes the existing root lease, rejects unsettled work and a changed model
route, and returns effective readback. Explicit choices outside the native option
list are refused; null resets that setting to the profile default.

`SessionControlStore` owns only the per-conversation setting overrides, in the
existing runtime root. Its filenames are session-id digests; atomic writes retain
the other setting. It does not rewrite native history/model metadata or another
conversation. Profile configuration remains the inherited authority.

`session_controls` supplies capability options from native fast-mode route gates.
Normal, Fast, Auto and First turn appear only on an eligible route. Ultrafast is
also model- and transport-gated; Codex app-server follows its native tier table.
Requested and effective tier are distinct. A requested tier unavailable on a new
route does not send a paid override; delivered tier stays unknown until the
provider reports it. The runner applies the choice to newly constructed and
reused actors without rewriting past messages or the system prompt.

Approvals describe the approval engine, not workspace/tool restrictions. The
operator root binds a task-local policy and attaches the existing native gateway
queue. Manual/Smart/Off retain native detector, guardian, allowlist and deny-floor
semantics. The pending read replays the existing queue without taking the runner's
profile lock. Responses address one request id and accept only the advertised
Allow once/Deny choices. Expired, foreign and duplicate responses cannot grant an
action. Timeout, withdrawal and turn interruption fail closed; scope cleanup wakes
waiters. Hosted policy and YOLO bypass are reported; governed/bypassed settings are
read-only. Managed profiles do not consume saved chat overrides.

The two additive upstream doors are recorded in the footprint ledger. No upstream
PR was submitted. Launcher consumption and UI evidence live in
`EterniaLauncher/docs/mission_control/evidence/session-controls-2026-10-14.md`.

## Verification

Focused native run: 11 tests passed, including a real `ProfileAgentRunner` whose
injected model transport calls the real command guard. It waits on the native
queue, rejects a foreign owner/stale id, honors both Allow once and Deny, and
observes the selected speed in its request overrides. No provider call or terminal
command was executed. The native settings reply captured by this run is vendored
into the Launcher adapter test fixture.

Killing control: replace the runner's `session_approval_scope` argument with None.
Both real-runner tests fail waiting for the native queue (2 failed, 9 deselected,
22.73 seconds, exit 1). Restored before qualification.

The shared process-wide run lock remains an execution-isolation limitation: a
human wait can block unrelated root runners. Its refactor is filed in the runtime
queue with the existing scope/lock symbols; this change does not relax profile or
cwd isolation.

Full landing qualification is recorded below after the final candidate runs.

### Landing qualification

The whole-tree bundled gate ran 1,118 files: 15,387 passed, 39 failed, 77 skipped,
zero errors. The new controls passed within it. The office manifest failures were
fixed by regenerating the checked fixture with its actual producer (215 methods).
The remaining failures used an excessively long Windows temporary path inside a
Git checkout: checkpoint refs exceeded Windows path limits, and project discovery
correctly found that checkout. Rechecking all twelve failed files plus the controls
with a short temporary root outside a project passed 861 tests, zero failed.
This records the first-attempt failures rather than calling that gate green.

A further mutation removed `value` from the required setting fields: the omitted
value case failed (one failed, eleven deselected, exit 1), proving omission could
silently reset a saved policy. Restored. Final controls/footprint run passed 21
tests, including all twelve controls cases. CLI contract freshness and documentation
citation adjacency passed. Changed production modules pass ruff; code health
reports zero blocking and zero advisory findings.

The repository-wide lint gate remains red in `footguns`, `no-tmp` and `ruff`.
An unchanged-main control reproduced all three, including 2,121 ruff findings;
repair ownership is recorded in the fork hygiene queue. The normal Windows console
also reproduced the already queued output-encoding fault; UTF-8 supplied readable
diagnostics. No lint rule or test baseline was weakened.
