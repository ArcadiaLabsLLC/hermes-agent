# Provider access boundary — October 1

Status: implemented and narrowly qualified; repository-wide exceptions below.
No upstream PR submitted.

## Upstream audit

Compared with NousResearch main `29b951d28cafe13e3f01a4188a7733a92cbc5414`.
The source was fetched for inspection, not merged.

- `agent.secret_scope` owns profile secrets. Rebinding it to the operator would
  expose operator tool credentials to agents; it is not a provider-only seam.
- Secret-source plugins hydrate env-shaped secrets. They do not select OAuth
  files or project provider definitions.
- `hermes_cli.auth` has a read-only global-store fallback. Profile-local grants
  still take precedence; this is not Eternia's explicit single-owner policy.
- `ProviderRegistry` and `PluginContext` already own scoped registration,
  replacement and unload. The new access contract reuses them.

## Boundary

Native provider readers depend on `agent.provider_access.ProviderAccess`, not
Harness modules. Its three operations select a provider secret, a credential
file, and a read-only configuration view. No extension preserves each reader's
existing fallback. An empty bound secret is authoritative; conflicting bound
extensions or access errors must not borrow another authority.

`plugins/eternia-harness` registers `SharedProviderAccess`. Harness retains its
existing auth-home authority and provider projection. Native credential pools,
refresh locks, storage, catalogs and model resolution retain their ownership.
Tool secrets, model preferences, session identities and native recovery are not
moved or reimplemented. Existing secure-store seams are separate, unchanged debt.

Only the generic contract, plugin registration method and native call sites are
upstream candidates. Eternia policy and its integration tests stay downstream.
This does not certify the rest of the fork as upstream-ready.

## Contribution boundary

The shared-provider changes trace to fork commit `ccca4c3138` (September 29).
Git attributes it to the configured author; that alone does not identify which
human or assistant wrote each line. This cleanup claims only its own diff.

For a future upstream proposal, offer the generic port, registrar, native reader
hooks and independent contract tests together. Do not send the Harness adapter,
operator-home policy, Launcher wiring or the whole fork diff. Rebase that proposal
against then-current upstream and recheck its native alternatives and tests.
Native compute receipts, session identity and recovery fixes remain native work;
moving those into Harness would duplicate native authority.

In particular, `tui_gateway.compute_model_selection` handles native `config.set`
receipts under the native execution lock. It contains no Launcher or Harness
imports and forwards through the existing compute supervisor. Its two native
callers require native session internals; moving it into `agent_runtime` would
make those callers depend on Harness and would not remove a parallel owner.
Retain it as a generic native-fix candidate, not Eternia product policy. The older
queue's proposed move needs this distinction; a new file under a native package
is not by itself evidence that its behavior belongs in Harness.

The port participates in the existing enabled-plugin lifecycle. With no registered
bound extension, standalone Hermes retains its defaults; it does not interpret
Eternia's auth-home setting itself. Bound extensions must return an authoritative
empty value for missing secrets. They must not expose tool secrets through this
provider-only boundary.

## Repaired isolation gap

Upstream's global OAuth fallback could bypass an empty explicitly selected owner.
Both auth.json and Anthropic's root OAuth lookup now resolve through the same
access port. Bound reads cannot borrow that other root; unbound profiles keep
native fallback. Anthropic API-key reads also honor the selected owner instead
of the agent profile's key. No token is copied or migrated.

## Validation setup

The previous local test interpreters were unavailable. Fresh PM environment
creation stalled before building: a bounded traceback located it at assignment
to `SSLContext.keylog_filename`, reached by `pm.downloader` at import time.
The inherited `SSLKEYLOGFILE` named a Windows monitoring pipe. Initializing the
platform verifier did not unblock it; this was not certificate validation.
Only identified validation builders were stopped. The retry excludes that debug
setting from the test-builder environment, matching the hermetic runner's scrub.
System settings and TLS verification stay unchanged. No production process,
profile or credential was modified.

## Qualification

Windows, Python 3.14.7, hermetic per-file runner, one worker. All credentials were
synthetic; native execution used a loopback provider and temporary profiles.
No live app, installation, sign-in or user profile was changed.

- Provider regressions: **182 passed** across nine files, including standalone
  OAuth fallback, scoped keys/configuration, credential refresh and model choices.
- Native execution: **8 passed**, private/shared × inline/compute plus in-process
  A→B→A, model changes, retirement and reopening without execution.
- Plugin/architecture batch: **1,368 passed, 1 failed, 2 expected failures**.
  Scoped plugin lifecycle, import direction, file/function size, frozen homes,
  tombstones and upstream footprint pass. The failure is the existing duplicate
  private-helper-name assertion (`_flag`, `_model`, `_owner`).
- Final shape/doc batch: **19 passed, 2 failed**. Thin namespace and docket pass;
  Discussion routing-ladder drift remains. No waiver or enlarged size fixture.
- Config-writer gate passes; changed-line profile-scope audit: **0 findings**.
  New production files: 67 and 25 lines; longest function: **8 lines**, maximum
  control nesting: **1**. Ruff F and `git diff --check` pass.
- Citation adjacency retains the already-queued Toolsets citation failure in
  `05-chat-turn-lane.md:296`; the same failure reproduces on untouched main.

Untouched main `29dfcf0dd5` reproduces the duplicate-name and both routing-ladder
failures. Its newer Work commit also contributes `_answer` to that same existing
duplicate-name assertion. These are not claimed fixed or masked by this change.
Full-suite and desktop acceptance were not rerun; the prior host-freeze boundary
still excludes unsafe updater/publication testing on this PC.

Red controls, restored before final green runs:

1. Before the OAuth fallback fix, the empty-owner regression returned the global
   store's synthetic `other` entry instead of `[]`.
2. Ignoring registered provider access fails both independent contract tests
   (missing projection; expected access error not raised).
3. Bypassing the Anthropic owner read returns `test-agent-a` instead of
   `test-account-a`; restoring the root fallback violates the no-borrow assertion.

Logs: `C:/Users/Multi/.codex/tmp/provider-access-{regressions,native,gates,final-shape}.log`,
`provider-access-{owner-red,mutation-registration,mutation-anthropic}.log`, and
`provider-access-main-{baseline,shape-baseline}.log`. Test setup evidence is under
`C:/Users/Multi/Documents/Codex/2026-09-27/continue/provider-boundary-qa/`.
