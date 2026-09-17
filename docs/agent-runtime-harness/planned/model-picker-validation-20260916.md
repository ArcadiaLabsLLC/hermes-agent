# Model picker validation receipt — 2026-09-16

Status: feature branch only; NOT approved to merge. The operator's local worker must inspect and validate both repositories before either product branch lands. Plans are already on main. This evidence note is not a work queue.

Implementation contract: `model-picker-policy.md` in this directory. Client contract: `EterniaLauncher/docs/mission_control/planned/agent-model-picker-catalog-ux.md`.

## Code under test

Branch: `feature/agent-model-picker-catalog-ux-20260916`.

- First implementation: `b8d68649d2744febfb3bcad004c3f1195c461d6f`.
- Final runtime code/test revision verified here: `f8dac4a5d2aae976c55a292157f4740173eb717c`.
- Original main/planning baseline: `0a86b7e1374a3b7860cd37b8d89776ddc9255ea1`.

This receipt is a later documentation-only commit. Do not confuse its SHA with the executable revision tested above. Any later code change requires revalidation.

## Executed, not merely proposed

GitHub-hosted Ubuntu, fresh checkout, Python virtual environment installed using `python3 -m venv .venv` then `.venv/bin/python -m pip install -e '.[dev]'`. No operator home, credential, live model endpoint, Windows process, or local primary checkout was used.

1. Run `35060705379`: compileall plus four focused files, **24 tests passed, zero failed**. The job applied the reviewed patch to the exact planning baseline and pushed only the feature branch. The old source-snapshot jobs were NOT tests and are not evidence of correctness.
2. Run `35061298814`, pinned to `f8dac4a5...`: **six focused files, 41 tests passed, zero failed**, retries disabled:

```sh
scripts/run_tests.sh -j 2 --file-retries 0 \
  tests/hermes_cli/test_model_picker_policy.py \
  tests/hermes_cli/test_model_picker_visibility.py \
  tests/hermes_cli/test_provider_catalog.py \
  tests/hermes_cli/test_codex_models.py \
  tests/hermes_cli/test_codex_cli_model_picker.py \
  tests/test_provider_visibility_v2.py
```

3. Billing mutation on that same isolated checkout: changed the account-route projection to catalog billing. `test_descriptor_projection_matches_shared_wire_fixture` failed with `{'billing_mode': 'catalog'} != {'billing_mode': 'account'}`; runner exit **1**, one failed/five passed. Restored the original file; all **six** policy tests passed again. The mutation was never committed or pushed.
4. `.venv/bin/python scripts/doc_cite_adjacency.py --exclude archive --exclude planned`: **passed**, zero unwaived failures and zero stale waivers. Existing 65 waivers remain unchanged.
5. `.venv/bin/python scripts/dump_cli_contract.py --check`: **failed** on the feature and, in a separate clean baseline run `35061781073`, on untouched planning main. The two captured failure outputs are byte-identical. The drift is an unrecorded `--sync-imports` store_true flag in the committed argparse dump. This feature changes no parser or CLI-contract fixture. Do not regenerate or waive it blindly; inspect the owner change and synchronize both fixture copies through the established contract process.

Action run URLs use this repository's `actions/runs/<run-id>` path. Full artifacts were retained for one day and exported to the initiating chat; this receipt preserves conclusions after artifact expiry.

## End-of-implementation runtime audit

- One small policy module, one additive field at `provider_login_catalog`'s existing descriptor emission seam. Existing visibility envelope stays `hermes.provider_visibility/v2`; no RPC, config migration, cache, model-setting write, or inference-loop change.
- Codex membership delegates to the canonical no-token discovery function. Tests exercise actual CODEX_HOME file resolution A→B→A and trap attempted API discovery. No duplicated current model list or account-entitlement claim.
- Malformed discovery fails unavailable rather than widening to the public API catalog. Empty compatibility lists remain meaningful. Error projection carries exception class only. Failure isolation is exercised through the real `build_provider_visibility` producer, not just a helper.
- API-key Anthropic remains catalog-billed despite its external login flow. Account routes are explicitly classified; authentication shape alone is not the rule.
- Synthetic policy fixture is shared with Launcher. The worker must compare actual final copies byte-for-byte.

## Still required before joint landing

Run the repository-prescribed broad scope (`tests/agent_runtime tests/hermes_cli tests/cli tests/state`) with `scripts/run_tests.sh`; it was NOT executed in this receipt. Resolve/revalidate the existing CLI-contract gate. Inspect the paired Launcher implementation and its receipt, complete its full fake tier and real Windows Stage C visual proof, and verify no regression to model override targeting, provider management, or the live serve boundary.

A passing focused suite is not a waiver for an unrun or failed required gate. Both repositories must pass before either merges. Recheck remote heads, use isolated worktrees, and never force main. Fast-forward Hermes then Launcher; cross-repository pushes are not atomic, so stop and report exact partial state if the second fails. Reconcile the operator's primary checkouts safely only after successful landing. This chat did not modify those checkouts.
