# Direct tool-token coverage repair — 2026-10-08

## Ownership and scope

Separate integration prerequisite, claimed before code in `497a8ad677`; based on current main `74a64be15e` plus the explicit warm-prep lane dependencies. The main advance only added an unrelated relay cancellation queue row, preserved by both rebases. Product bytes are unchanged by those refreshes.

The history gate identified a deleted last direct reference to `hermes_cli.tools_config._estimate_tool_tokens`. Same full gate file on the earlier lane and untouched `633fdda0fe` reproduced one identical violation. Restore meaningful direct contract coverage in a fork-owned downstream file; do not suppress tombstones or edit production code.

## Coverage and limits

Four tests use a fresh real `ToolRegistry`, isolated cache/home, and an inert builtin-discovery import. A deterministic tokenizer boundary records the full OpenAI function wire JSON and checks the requested `cl100k_base` encoding name. This verifies serialization/delegation and counting, not actual BPE tokenization. The optional tokenizer is absent from the shared test interpreter; no dependency was installed.

Contracts: empty registry then registration; full wire wrapper and warm cache reuse; recalculation after registry generation changes; separate profile catalogs at the same generation; unavailable-tokenizer fallback. No changes to effective tools, prompts, credentials, selection or persistence.

Named one-file shared-interpreter lane: four passed, exit 0 in 4.0 s. The initial package-style import exercised the function but was not visible to the direct-reference scanner; the explicit module import fixes that without changing the tests' behavior. Corrected test plus full tombstone-registry file: 31 passed, exit 0 in 63.3 s. Both controls were rerun successfully after the import change. Touched-file ruff: PASS. Isolated characterization copy: four passed.

Positive control removes the full function wrapper in a throwaway production copy: expected 187 deterministic units but got 153, exit 1. Killing mutation freezes the generation component of the cache key: refreshed cost remains 187, failing `187 > 187`, exit 1. Both changes are absent from the repository and excerpts are in the CHANGE commit body.

## Integration proof

The first combined gate attempt was stopped after 222 files when CI exposed the import mismatch; its log is preserved. The corrected ready batch must run the whole-tree fork landing gate; the selected scope excludes the four workstation-freeze P0 files. Gate results, violation comparisons and live checks belong to the execution artifacts. No complete passing batch or final latency is claimed here before that run.

The 250 ms goal remains unmet in existing receipts. This repair changes tests only. The timing lane enables the next measured decision after integration; its fixture overhead is not production evidence.
