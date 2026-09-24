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
