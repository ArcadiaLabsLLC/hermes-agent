# Provider setup verification — 2026-09-25

Scope: canonical noninteractive provider authentication and stable provider IDs
for the shared Launcher service. No installed profile, credential or Desktop
store was changed. The Launcher pins the selected installation and auth home.

## Changed behavior

`provider_browser_login.py` delegates to existing Codex PKCE/device, Nous,
xAI and MiniMax flows. It suppresses helper output, emits bounded typed events,
and persists fresh grants only in the selected auth store. Login-health rows
now carry a canonical `id` separately from their display `name`; clients do not
need a second alias catalog. Unsupported browser flows remain unsupported.

## Passing checks

- Initial canonical auth/catalog/PKCE-loopback coverage: 27 passed.
- Final identity, visibility, browser and noninteractive coverage: 39 passed.
- Final CLI/payload contracts, size, import layers and identity: 42 passed.
- Upstream/public-plugin/thin-namespace boundaries: 9 passed.
- Broader boundary/docs checks: 84 passed, with the existing frozen-home
  witness failure described below. Changed-module Ruff checks passed.

Mutation evidence: dropping the event home and allowing canonical helper output
to escape produced 7 failures / 4 passes. Removing stable login IDs produced
`KeyError: id`. Restored implementations pass. Live external consent and real
credential writes were not exercised; canonical flows used isolated fixtures.

## Full-scope result, not an all-green claim

`scripts/run_tests_bundled.sh tests/agent_runtime tests/hermes_cli tests/hermes_state`:
673 files, **10,564 passed, 84 failed, 31 skipped**, no collection errors.
All 21 failing files also fail on unchanged `284cb3f2f8`: two baseline runs
total **1,316 passed, 83 failed, 2 skipped**. TLS varies by one socket failure;
this comparison proves pre-existence, not the cause of every assertion.
The subsequent rebase contains documentation only, with no touched-code overlap.

| Existing cluster | Failing files (under `tests/`) |
|---|---|
| Gateway/TLS/real sockets | `agent_runtime/test_gateway_tls.py`, `test_gateway_media_fetch_e2e.py`, `test_gateway_peer_cross_install_chat_e2e.py`, `test_gateway_peer_cross_install_media_e2e.py`, `test_gateway_peer_two_roots_e2e.py`, `test_local_llama_adapter_gateway.py`, `test_serve_gateway_chat_reply_lanes.py`, `test_serve_gateway_lane.py`, `test_serve_gateway_peer_lane.py` |
| Existing fixture/history debt | `agent_runtime/test_core_fingerprint_cache.py`, `test_no_kanban_dependency.py`, `test_no_midtest_monkeypatch_undo.py`, `test_scope_use_serve_acceptance.py`, `test_tombstone_registry.py`; `hermes_cli/test_flag_binding_boundary.py` |
| Provider seam fixtures | `hermes_cli/test_external_process_provider_seam.py`, `test_model_picker_visibility.py`, `test_plugin_provider_picker_admission.py`, `test_plugin_provider_picker_residue.py` |
| Auth test classification/environment | `hermes_cli/test_anon_sign_in_flow.py` (strict XPASS); `test_auth_codex_self_heal.py` (certificate issuer failure) |

The separately run frozen-home gate still names `gateway/mirror.py` and
`tui_gateway/server.py`, as the skills verification did (that note was deleted with the
ACP surface, lane ACP-DROP; last present at `f6894e3497`).
Existing queue rows retain gateway, fixture/history, empty-WAL and frozen-home
work. New rows record provider seam fixtures and auth-test classification;
no skip, xfail or assertion was added to conceal these failures.

## Native integration

Launcher used the real Hermes entry point with this candidate on `PYTHONPATH`,
an isolated `.hermes/profiles/provider-home-qa` and isolated runtime root.
Native inspection exposed display labels being mistaken for IDs; fixing the
producer and consuming `id` removed duplicate rows without a Launcher catalog.
Launcher presentation, scope cancellation and native limits are recorded in
`EterniaLauncher/docs/companion/planned/PROVIDER_HOME_SLICE_2026-09-25.md`.
