# Scoped chat Work

The Eternia harness resolves conversation links; native Hermes owns tasks,
assignment, execution and lifecycle. This extends the existing Work adapter,
without a Companion engine, another task store or workflow orchestration.

Contract: [Conversation-scoped Work](../agent-runtime-harness/03-transport-and-wire.md#conversation-scoped-work).
Launcher receipt: `EterniaLauncher/docs/companion/planned/SCOPED_CHAT_WORK_2026-10-01.md`.

## Verification

Six new runtime tests cover native route/account/home isolation, stable-session
admission, task origin, replay conflicts, scope refusal and exact operator
validation. The focused Work/RPC/import-boundary set passes: **18 tests**.
The generated RPC manifest adds only `runtime.work.context`.

Positive control: replacing native creation's `session_id=session` with
`session_id=None` makes `test_submission_and_agent_created_work_share_native_origin`
fail `assert None == 'native-a'` (one failed). Restored before the passing run.

The canonical suite completed **2,178 files: 24,717 passed, 38 failed,
734 skipped**. Of the 38 assertion failures, **34 reproduce on clean primary
`734c4537aa`**. Four are the previously documented checkout-dependent probes:
two fleet tests classify the shared interpreter as external, and two updater
probes reach that interpreter's primary checkout before their mocked hooks.
The 14 collection/teardown failure files reproduce on primary. A browser-port
probe failed once and passed the runner's retry; it is not counted among the 38.

After rebasing onto `734c4537aa`, tooling and the private RPC checks report
**1,313 passed, three existing failures**. The Work routing ladder and
unrelated private `_answer` name collision were repaired without waivers. The
remaining helper-name and discussion-ladder failures reproduce on primary.
Citation adjacency retains the already-queued Toolsets citation failure.
The mutation inventory selects no registered changed-line claims; the explicit
origin control above supplies this slice's red. Ruff F and the 18-test focused
Work set pass after the repairs. The refactor census was recorded.

Logs are retained under ignored `qa-artifacts/scoped-chat-work/`.
