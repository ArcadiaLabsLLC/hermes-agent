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

In progress. One worker; synthetic credentials and temporary homes only.
Removing terminal-evidence attachment makes all four native regression cases fail.
Restoring the RPC child's old argv makes its real-parser dispatch test fail.

### Existing baseline failure

`test_profile_runner.py::test_tool_io_pathological_result_never_kills_the_tool_event`
fails on unchanged main `0238e55359` as well as this branch on Python 3.14.7.
Its 4,000-level list retains a `tool_result` where the test expects omission.
Provider changes do not touch that serializer; the baseline is not waived.
