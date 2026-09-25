# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY**.

## Frozen inputs — 2026-09-25

- F fork main: `6b3157532088540d22cf69036c26247079973e5f`
- S cycle start: `666f46eb51a3814dcde3f7ddc382a86506602746`
- U upstream main: `59004a62356f3a4697ab0fe8ad5086d2b405e2a6`
- S/F merge base: `b93ce5e66c3e405c0ea3fb30ef43458a601f5243`
- fork refresh: `3b61db95320ae2376359aa1caca7831b26d01a3f`
- TUI reconciliation: `6930fbf37ec7c1a5c901e94c5942dd148edbb3e4`
- API streaming reconciliation: `598128c0c4a9930c2d8c36ab4906d2218de1d6a7`

The fork refresh is a two-parent commit with prior sync first and current fork main second. Fork main itself was not changed.

## Completed this cycle

### ALREADY_RESOLVED — TUI fanout source

Commit `6930fbf37ec7c1a5c901e94c5942dd148edbb3e4`.

Paths:
- `tui_gateway/transport.py`
- `tui_gateway/ws.py`

Before the upstream fanout series, fork main matched the upstream baseline exactly in both files. The branch now carries frozen-upstream blobs `689f5614299c77f3f6a4c779176938b537a8cb4d` and `f21dfb24abc6a1f4baa68195bd7483975bbc7f61`.

The companion test `tests/tui_gateway/test_multi_client_fanout.py` already differs on the fork, so it still needs a combined local reconciliation and focused run.

### ALREADY_RESOLVED — Chat-Completions final fallback

Commit `598128c0c4a9930c2d8c36ab4906d2218de1d6a7`.

Paths:
- `gateway/platforms/api_server_openai_routes.py`
- `tests/gateway/test_chat_completions_final_fallback.py`

Fork main exactly matched the parent of upstream `e42b61be434cdb620b964837108091169554eb28` for the source path, so that focused upstream behavior and its new test were safe to carry. Later upstream edits to the same API owner belong to a broader run-SSE stack and remain pending.

Also resolved by the fork refresh: `agent/stream_delivery.py` now matches frozen upstream exactly.

## Work queue

### LOCAL_GENERATOR_REQUIRED

Dependency source and generated lock still differ:
- sync `pyproject.toml`: `f02d9b51edc104660d84f3f79f6b85ba9d863dca`
- upstream `pyproject.toml`: `3380055aa40d8c7c6ed783b85a07d8060a70188b`
- sync `uv.lock`: `852ac06d0e91c52da50448d9e7bf0251df00b704`
- upstream `uv.lock`: `953221d85bd0dc70e5ff2c929e5c7245f5f4d235`

Reconcile the dependency source first, then regenerate the lock with the repository's canonical workflow in a real checkout.

### LOCAL_TEST_OR_RUNTIME_REQUIRED

- `tests/tui_gateway/test_multi_client_fanout.py`: combine fork and upstream expectations, then run focused TUI gateway coverage.
- Later API-server/run-SSE work after `e42b61b`: review as a coupled owner stack.
- `gateway/run_busy.py`: current sync blob `537d4344136dbd841e4af450447729319be341e4`; upstream `66ae8d9cbe6d05ccd724cb7c30ecf9051540dc71`. Combine current fork routing behavior with upstream stop/dispatch behavior and run focused gateway cases.
- Hosted context-window work remains coupled to the fork's extracted orchestration owner.
- Auxiliary/billing/credits remains a coupled owner stack.
- `agent/model_metadata.py`: current sync `f1e6f2bb102f2efc4656f9f1446a4c6494c6f72b`; upstream `1ab7008dbd9974e6a0505a53cd927ecf0285bfc5`. Both sides moved; requires a semantic merge.

### SAFE_CLOUD_RESOLUTION candidates to revalidate next cycle

- `agent/video_gen_provider.py`: branch and frozen upstream differ only in current package-manager guidance.
- `agent/web_search_provider.py`: frozen upstream has a stricter multiplex profile-scope guard.

### OPERATOR_DECISION_REQUIRED

None newly proven.

## Verification

Performed: instruction review, F/S/U freeze, ancestry and merge-base checks, fork refresh, blob-history checks for both reconciled source slices, live-ref checks before writes, and post-work F/U re-reads.

Not run: Python tests, focused TUI/gateway tests, JS/Electron tests, generators, contract checks, or runtime probes.

## Continuation

Continue only on `automation/upstream-sync`. Preserve its history and existing work. Complete generated artifacts and focused execution before claiming a source candidate. Frozen upstream `59004a62356f3a4697ab0fe8ad5086d2b405e2a6` is not yet claimed as fully integrated.
