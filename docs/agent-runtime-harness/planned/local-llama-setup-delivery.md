# Local llama setup: implementation checkpoint and consumer contract

2026-09-15. **Backend protocol implemented and focused-tested; integrated UI
acceptance still pending.** Runtime remains owned by `local_llama.manager`, never
the upstream independent supervisor. Reused upstream asset selection and binary
location helpers; download/extraction is staged, digest-pinned and cancellable.

## Consumer packet

Schema `hermes.local_llama.setup/v1`, same aimed authenticated JSON-RPC lane.
Method prefix `runtime.local_llama.`. `setup.capabilities` is read-tier; all other
new methods are console-tier. Peer calls are refused. Strict accepted parameter
keys are in `agent_runtime/local_llama/setup_rpc.py: FIELDS`.

- `setup.capabilities {}`: `features` boolean map, automatic_platforms,
  unsupported_reason. Initial automatic platform Windows x64; existing binaries
  may be validated/adopted elsewhere. Offline archive import/browser are false.
- `installations.detect {}`: bounded configured/managed/PATH candidates. Version
  is probed for configured path; other candidates remain unvalidated. Failed scope
  is inconclusive, never proof of no installation.
- `installations.validate {executable_path}`: `installation` version/hash/features,
  `validation_token`, expires_in_seconds=900. Does not change config/start llama.
- `hardware.get {}`: host OS/architecture/RAM and explicit unknown GPU facts.
  No guessed GPU compatibility or memory-fit guarantee.
- `host_paths.validate {path,purpose}`: purpose installation_parent|model_root;
  normalized_path, exists, writable, free_bytes. Parent must already exist.
- `releases.list {}`: releases with release_id/tag/stable_alias/prerelease and
  variants `{variant_id,backend,download_bytes,artifacts}`. Artifacts are official
  asset IDs, names, bytes and SHA256; private download URLs are not client inputs.
- `installation.plan {tag,release_id,variant_id,destination_parent}`: `plan` pins
  exact asset bundle, host parent/final directory, revisions, expiry and warning_ids.
  It performs no download. UI displays required/free bytes and chosen version.
- `installation.apply`: guard fields plus plan_id, plan_revision,
  acknowledged_warning_ids. GPU variant requires explicit cuda_driver review.
  Replies with `operation`. Success installs **inactive**; activation is separate.
- `installations.activate`: guard fields, expect_inventory_revision, and exactly
  one of installation_id or validation_token. Server off/zero turns required.
  Retained installations support rollback through this same operation.
- `operations.cancel {request_id,operation_id}`: idempotent target-bound request.
  Reply operation; accepted cancellation is not completion. No cancellation during
  publication/activation, and no invented model-load cancellation.
- `setup.status {request_id? OR operation_id?}`: inventory, inventory_revision,
  active_installation_id, active_operation, requested_operation, lookup_state.
  Historical missing receipt returns not_found plus fresh current operation.
  Never mint another request ID merely because lookup is missing/transport failed.

Guard = request_id UUID, expect_epoch, expect_revision, expect_config_revision
from a fresh lifecycle `status`. Plans additionally check their ORIGINAL config
and inventory revisions. Epoch changes invalidate unaccepted plans. Active setup
reserves the same mutation/inference owner used by legacy RPCs. Existing v1 status
has additive `active_operation`, while `operation` remains exact requested history.
During setup the legacy busy projection uses valid v1 running state; detailed
cancelling/cancelled are isolated to setup schema. In-flight state is never readiness.

Setup operation: operation_id/request_id/kind (install|activate), state
(queued|running|cancelling|succeeded|failed|cancelled|interrupted), phase, sequence,
bytes_done/bytes_total nullable, can_cancel, accepted_at/finished_at, error/result.
Terminal result includes cleanup and retained_paths; installed result includes
installation_id and activated=false. Existing `logs.get` includes sanitized setup
phase/result summaries. It does not expose arbitrary files/native stdout.

Errors preserve JSON-RPC envelopes and `error.data.reason`; accepted errors settle
the operation. Recognize stale_revision, plan_changed/expired, operation_busy,
active_turns, server_must_be_off, cancel_not_available, digest_mismatch, disk_full,
path_conflict, unsafe_archive, recovery_required, rate_limited. Keep user drafts.

[Producer fixtures](local-llama-setup-fixtures.json) were emitted from an isolated
real official b10964 CPU installation/activation, with host paths sanitized. They
cover setup capabilities/status, lifecycle status, plan, and terminal operations.
Unknown/empty/permission and cancellation cases are exercised in setup/gateway tests.
Consume typed DTOs through the existing aimed transport; no shell or download code
belongs in Launcher.

## Evidence

- `scripts/run_tests.sh` (Git Bash) with setup, manager, config, RPC and gateway
  targets: 54 tests passed, exit 0.
- After recovery/tamper/TLS coverage was added: setup + gateway targets, 22 tests
  passed, exit 0 (overlaps prior run; not an additive total).
- `scripts/probe_local_llama_setup.py --tag b10964 --backend cpu --output <isolated-artifact-directory>`:
  exit 0; official SHA256 verification, safe extraction, binary version/router
  qualification, inactive publication, explicit activation, server remained off.
  Receipt retained in local Codex artifacts. No live runtime/config/model touched.
- Python compileall over the changed package passed. Full integrated Launcher
  flow, real GPU variant install, second physical host and Stage C remain pending.

## Limits and implementation decisions

Original proposal is narrowed explicitly: no arbitrary offline archive import,
remote file browser, range-resume, uninstall/automatic pruning, or fabricated model
fit estimates. Existing executable adoption works offline. Read-only hardware
returns uncertainty; selected CUDA requires driver review and real validation.
Known-good versions remain on disk; no automatic restart or model reload.
Interrupted staging is retained/reported for inspection, never deleted on startup
from an unverified path. Config/revision publication is journaled; conflicting
external edits fail closed. These decisions must remain visible in the UI.
