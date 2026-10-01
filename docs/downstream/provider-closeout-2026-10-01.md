# Provider closeout — October 1

Scope: Harness setup commands, native terminal-error evidence and selected-provider
qualification. Profiles, credentials, account ownership and UI design are unchanged.

## Command ownership

Non-interactive setup is `hermes harness auth set-key|login`. The Harness parser
delegates to the existing credential lifecycle and browser drivers; native
`hermes auth` keeps its own commands. Launcher argv and the RPC sign-in child use
the same plugin command. Secrets remain on stdin, never argv or receipts.

## Terminal evidence

`agent.turn_api_error` attaches the native classifier's evidence to the terminal
result through `agent.provider_failure.attach_provider_failure`. No captured
last-error state, method wrapping or display-text equality remains in
`agent_runtime.profile_runner`. Recovered attempts carry no terminal record;
interrupt and shutdown retain their own meanings. Harness consumes the result
without reclassifying providers.

Upstream `5690810779` was inspected independently: its exception handler and
classifier do not yet carry this terminal record. The additive native fix is a
generic upstream candidate; Harness command registration and owner policy are not.
No upstream PR was submitted.

## Qualification

One worker; synthetic credentials and temporary homes only.

- Focused provider/runner checks: 172 passed; one unchanged baseline failure below.
- Native/profile regression checks: 196 passed, including private/shared access,
  inline/compute execution, A→B→A isolation, model changes and reopening.
- Contract, import-boundary and consumer-verdict checks: 118 passed.
- File/function-size ceiling: 5 passed. Ruff F and whitespace checks pass.
- Final auth/namespace checks: 17 passed. Adding a secret-valued CLI flag makes
  the parser safety test fail; the mutation was restored before this green run.
- The actual `python -m hermes_cli.main harness auth set-key` process saved a
  synthetic key to the isolated home, exited 0 and returned no secret.
- CLI fixture: 208 command paths; only the three Harness auth paths are added.
  Launcher consumes identical bytes and tests its emitted arguments against them.

Removing terminal-evidence attachment makes all four native regression cases fail.
Restoring the RPC child's old argv makes its real-parser dispatch test fail.

New production modules are 27 and 30 lines; longest new function is 20 lines.
The runner error module shrank from 176 to 38 lines. Neither a second classifier
nor a credential writer was added. Both native auth files match inspected upstream.
The upstream footprint drops from 173 to 172 files; no ceiling was raised.

Desktop verification is recorded in
`EterniaLauncher/docs/companion/planned/PROVIDER_CLOSEOUT_2026-10-01.md`.
No live OAuth grant, unsafe updater test or full-suite green is claimed.

### Existing baseline failure

`test_profile_runner.py::test_tool_io_pathological_result_never_kills_the_tool_event`
fails on unchanged main `0238e55359` as well as this branch on Python 3.14.7.
Its 4,000-level list retains a `tool_result` where the test expects omission.
Provider changes do not touch that serializer; the baseline is not waived.
