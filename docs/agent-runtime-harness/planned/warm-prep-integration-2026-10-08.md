# Warm send-prep batch integration — 2026-10-08

This batch reuses the existing canonical plugin-manager home key, adds bounded exclusive turn-context receipts, and restores four direct tool-token contract cases. Prompt, tool, provider and durability policies are unchanged. The 250 ms live target is not yet established.

## Verification

The whole-tree fork landing gate at `3072269227`: 1,070 files, 13,843 passed, two failed, 75 skipped, zero errors; exit 1. Stage 0: 905.3 s, 8 workers, 275 bundles, two solos, three isolated reruns, 98.3% utilization. The interrupted earlier gate is not a pass.

The same failing files on detached merge-base `74a64be15e` reproduce both exact nodes:

- `test_flag_binding_boundary::test_no_handler_collapses_an_absent_flag_into_an_empty_collection`: identical `hermes_cli/bundles.py:72` offender.
- `test_upstream_footprint::test_the_upstream_footprint_never_rises_and_the_fixture_follows_it_down`: both trees have 184 files / 959 deletions / four heavy files, against fixture 176 / 883 / four. Batch increment is zero in every ratchet dimension; its two upstream edits add 13 and four lines to already-carried files. No fixture ceiling was raised.

The full gate's visibility file was red bundled and green alone. Focused ordered phases / timing / visibility bundle comparison found intermittent stdout contamination. Preserved first-pass output on BOTH baseline and batch: 84 passed, the same timing-payload and finish-reason visibility nodes fail `json.loads` with Extra data. Canonical isolated reruns pass all 86 tests. The full gate's different first visibility node was not independently reproduced; its standalone authority passed. The leak remains filed, not fixed or hidden.

Restored coverage and the complete history gate: 31 passed. Positive wire-wrapper control and generation-freeze mutation both turn the new coverage red. Combined PR CI passed history and mutation checks. Fixture tokenizer coverage does not establish production BPE values.

`main` then moved only through relay queue claims; all three owned branches were rebased, retaining those claims and identical product/test bytes. Required tooling is rerun on the rebased batch; the expensive whole-tree gate is not repeated for a queue-only incoming change.

## Live acceptance

Refresh must show a new boot identity and the integrated code tree. Fresh service turns must carry resident actor reuse and matching turn/request receipts. A standalone CLI message is not warm-service proof. A reference-client service probe has no Launcher capability bridge; label that route and history gap explicitly. Preserve the original baseline and do not claim causal live savings from unmatched roots.

H4 tool-writer and H11 prewarm ownership remain with sol-runtime. Broader search-provider lookup remains measured but unchanged. Historical evidence: [initial measurements](warm-send-prep-measurements-2026-10-08.md), [attribution proof](warm-turn-context-attribution-2026-10-08.md), [token coverage](warm-prep-token-coverage-2026-10-08.md).
