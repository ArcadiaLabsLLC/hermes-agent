# ACP named-provider identity — qualification

Owner-requested correction for the Launcher's Intelligence model controls.
Baseline: `2455c606b4` (runtime code unchanged from `fa12c6c5a3`), Hermes 0.21.5.

## Contract and cause

The provider resolver already distinguishes `provider=custom` (transport) from
`requested_provider=custom:<name>` (endpoint identity). ACP dropped the latter
when constructing AIAgent, reporting models and persisting sessions. Two named
endpoints offering one model therefore became indistinguishable.

`acp_adapter/session.py::agent_provider_identity` projects that existing field;
it does not resolve aliases or inspect endpoints. Built-in providers retain
their resolved identity, including automatic selection. Session metadata adds
the requested identity only when distinct from the transport. Credentials are
re-resolved on restore, never persisted in metadata. Fork and unqualified model
switch use the same projection. `acp_adapter/server.py` consumes it.

This is a temporary generic core carry, recorded in the upstream-footprint
ledger and fixture. No ACP construction/readback/restore plugin hook supplies
the missing field. Retire the carry when upstream satisfies the same invariant.
No Launcher workaround, provider inspector or Mission Control routing change.

## Proof

- `tests/acp_adapter/test_named_provider_identity_downstream.py`: both tests
  fail on baseline. First: expected `custom:west`, got `custom`. Second: the
  unqualified switch cannot distinguish east/west. Both pass after correction.
  They cover credentials/endpoint retention, readback, fork, database restore,
  canonical/automatic identities and failed-build state preservation.
- Isolated real ACP process, loopback provider, no user credentials: connect
  reports `custom:east:qa-alpha`; apply/readback reports `custom:west:qa-beta`;
  a real reply uses `qa-beta`; a fresh process restores the exact named ID.
  Connect/apply made no completion request. Local metadata `/api/show` probing
  is not a conversation prompt. Only the test processes were stopped.
- Canonical runner over `tests/acp_adapter` and `tests/tools/test_find_shell.py`:
  192 passed, 5 failed, 3 skipped. The five failures reproduce unchanged in a
  clean baseline worktree: image resource-link Windows path, bare ping's native
  pipe handle, and the three symlink/lexical cwd-normalization cases in
  `test_session.py::TestSymlinkAliasNormalization`. They are not waived or fixed
  by this change. Baseline comparison: 33 passed, 5 failed across four files.
- Touched modules pass Ruff. Footprint: 214/1027/4 → 216/1032/4
  (files/deleted lines/heavy files), explicitly justified in the fixture.

Native Launcher acceptance and the installed-runtime cutover are separate
qualification steps; the loopback ACP receipt does not claim either.

## Installation qualification

The owner's `nekwo/hermes-agent` URL redirects to `ArcadiaLabsLLC/hermes-agent`;
these are not competing forks. The installed 0.19.1 checkout at `39fb8d426d`
predates the rebuilt fork history. A fast-forward update cannot reconcile it.
Its ACP shell-probe stdin correction is already present in 0.21.5.

Before testing, the profile root was backed up outside both installations:
10,945 verified files and 18 consistent SQLite snapshots. A disposable copy of
Amelia's database passes the current SessionDB migration with 1,447 sessions,
225,181 messages and `PRAGMA quick_check = ok` before/after. The live profiles,
skills, credentials and running gateway were not changed.

Qualification used Python 3.13.15 / SQLite 3.53.1, matching the installed
interpreter. The candidate also received the current locked equivalents of
the installation's messaging, voice, Edge TTS, Google and YouTube extras.

- Fork landing run: 558 files; 9,336 passed, 72 failed, 14 skipped. This is
  **not a green suite**. Certificate-pin mismatches dominate the gateway reds.
- Standalone loopback TLS reproduction, outside pytest: the received issuer
  is `Norton Web/Mail Shield Self-signed Root`, not the freshly generated
  self-signed Hermes certificate. The fingerprint mismatch correctly refuses
  that replacement. Untouched `2455c606b4` reproduces the TLS/scope failures.
  No certificate checks or antivirus settings were weakened.
- A stale `upstream/main` ref initially made upstream-owned code look
  fork-authored to scope gates. After fetching upstream and installing the
  missing messaging extra, a seven-file rerun passed 1,272 tests, failed five
  and skipped one. Tombstone, flag-binding, shared-monkeypatch and frozen-home
  gates pass. Remaining failures: four TLS/scope cases and the empty-WAL test;
  all five also fail in the unchanged baseline.
- `test_core_fingerprint_cache.py::test_a_key_written_with_an_empty_wal_matches_once_it_is_gone`
  unlinks a WAL already removed during setup on this SQLite build. The
  remaining 58 tests in that file pass in candidate and baseline.
- `test_docket_stage_claims.py` fails unchanged because the Stage 6 desktop
  owner-ruling heading cites no ancestor landing commit. This is a documentation
  gate, not an ACP regression. CLI/payload dumps, duplicate-helper and upstream
  footprint gates pass.
- The Launcher's real serve-frame check completed; only `ready.json` differs
  structurally from its committed capture. Its RPC contract remains 1, with
  52 added methods and none removed. The real Dart
  `MissionRuntimeRpcManifest.fromFrame` decodes all 78 methods and accepts
  every advertised method. Other changes are build provenance. This is a
  protocol check, not native UI acceptance; no Launcher fixture was replaced.

The correction was replayed onto `4e73892724` after the partner's concurrent
updates. Their new retired-scratch cleanup cannot select any row in Amelia's
verified database copy: its count for `agent_runtime_persona_chat_scratch` is
zero. The broader suite receipt above belongs to the earlier baseline, not a
claim that every incoming change was retested.

The seven post-rebase files (tooling gates plus the named-provider regression)
pass. The full suite's separately proven environmental/baseline reds remain
recorded above, not silently relabeled green.

A separate running Hermes Desktop installation was then observed at upstream
`749220ef00`, origin `NousResearch/hermes-agent`, with its own modified
`package-lock.json`. Its Python child also uses Amelia's profile. It is not the
Launcher-configured partner-fork installation. Neither installation was stopped
or overwritten; future cutover must coordinate writers to this shared profile.

## Approved cutover — 2026-09-24

The owner approved archiving the Launcher-linked installation while preserving
Amelia and leaving the separate Hermes Desktop installation untouched.

- Archived the complete 0.19.1 checkout and environment; repaired its linked
  worktree registrations without changing their source. No old Git history was
  reset or merged into the rebuilt fork.
- Installed the partner fork at the existing Launcher executable path, then
  fast-forwarded to `8573c5d415`. The incoming batch after `6f9aa0aa63` changes
  tests, tooling and documentation, not production modules or dependency pins.
  The installed environment reports 0.21.5 / Python 3.13.15 / SQLite 3.53.1.
- Took a second verified backup: 10,945 files and 18 SQLite snapshots. All 583
  checked Amelia skill, memory, hook, plugin, identity, config and credential
  files remain byte-identical after restart. Live history still contains
  1,447 sessions and 225,181 messages.
- Drained the old gateway through its planned-stop protocol, without forced
  termination. Restarted through its unchanged Windows Scheduled Task. The
  new gateway reports `running`, Telegram `connected`, and session store `ok`.
- Repeated the real ACP conversation/apply/restart smoke using the installed
  interpreter and isolated test data: all four checks pass.
- The installed Mission Control serve passes ready, ping and successful
  `harness status --json` through Launcher's isolated capture helper; its ready
  frame identifies `8573c5d415` and advertises 78 RPC methods.
- Hermes Desktop remains at upstream `749220ef00`; its existing modified
  `package-lock.json` has the same hash. Its files and configuration were not
  updated. Launcher still points at the original executable and profile root.

The live update is complete. Native Launcher UI acceptance was not rerun;
Norton's interception of pinned gateway TLS remains a separate local limitation.
No antivirus setting or certificate check was changed.
