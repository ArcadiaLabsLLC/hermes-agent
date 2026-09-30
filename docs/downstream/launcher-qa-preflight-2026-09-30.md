# Existing Launcher QA connection — 2026-09-30

The owner approved enabling root `agent_runtime.mcp_admission.enabled` and
registering the existing Launcher QA server only on `launcher-qa`. Both settings
were written through `hermes_cli.config.atomic_config_write`; the prior root
config was backed up and unrelated settings were preserved. No provider,
credential, persona, instance, session or active-profile binding changed.

## Existing conversation

The CLI must select `base` to resolve the configured `qa` persona on this host.
The active `amelia` catalog omitted it; `unsupported_persona` did not mean the
saved instance had disappeared. `personainst_qa` still owns session
`persona_chat_personainst_qa_abd31617ae8a`, backed by `launcher-qa`.
Its successful identity turn supersedes the September 29 authentication blocker.

After connection setup, fresh CLI invocations stalled before the chat handler.
The existing authenticated socket service remained available. Its advertised
`runtime.chat.message` method reached the same instance and session, using the
repository's `ServeSocketClient`, live-target resolver and challenge-response
authentication. Service build: `7b500a16871d44d28c482ee29a77fc7d982b954a`;
source checkout inspected: `6c3fce3947`.

Requests `projects-qa-identity-20260930-04`, `projects-qa-denial-20260930-05`
and `projects-qa-admission-20260930-06` completed, with zero registered MCP
servers and zero Launcher QA schemas. The policy notice said `launcher_qa` was
admitted; this was not evidence of successful registration. Native acceptance
did not run, and no new agent or conversation was created.

## Missing runtime dependency

An inspection using the managed Python 3.14.7 interpreter and the canonical
dependency selector found no `mcp` import or installed distribution in the
selected environment. The existing QA agent separately reported
`mcp_sdk_unavailable` on request `projects-qa-sdk-20260930-07`; it did not execute
the requested installer. Its suggestion to fix config was not followed: the
connection declarations were already applied, and config does not supply an SDK.

The supported package-manager command is `hermes pm install --extra mcp`
(`pm/extras.py::install_hint`). Restore that dependency through the managed
installer, then refresh the service safely: MCP availability is process-cached
(`agent_runtime/mcp_admission/transport.py::mcp_sdk_available`). Re-prove the live
catalog and one non-mutating MCP call before requesting Launcher acceptance.

## Local startup stall

A bounded 20-second stack probe of the read-only CLI inspector stopped in
Python `ssl.create_default_context`, at the assignment to `keylog_filename`.
The caller was `pm/downloader.py` constructing its opener during
`pm.client.venv_is_current` / `hermes_cli.venv_sync.prepare_launch`.
`SSLKEYLOGFILE` was inherited and named a Windows device target. The trace
points to opening that logging target, after certificate loading; it does not
establish a certificate validation failure or who configured the target.

Only this follow-up's stalled CLI processes were stopped. No matching chat
journal existed for the stalled CLI request; the socket turns all settled.
TLS validation and diagnostic logging settings were not altered. The running
Hermes service and older Launcher/QA processes were not stopped. This is not a
diagnosis of the earlier Launcher's `launch_helper_wall_clock_timeout`.

Receipts are retained under ignored `qa-artifacts/launcher-qa-preflight-20260930/`.
Launcher qualification remains in
`EterniaLauncher/docs/companion/planned/COMBINED_ACCEPTANCE_2026-09-29.md`.

## Documentation checks

Diff whitespace and the added relative links/anchors pass. The repository's
citation-adjacency check reports one unwaived failure in the unchanged
`docs/agent-runtime-harness/05-chat-turn-lane.md`: its Toolsets paragraph cites
a line that no longer names the advertised tools. The checker, cited source and
canonical document were not changed by this follow-up; no waiver was added.
