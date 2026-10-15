# Downstream god-file refactor — running record (hermes half)

Field notes for [`downstream-god-file-refactor.md`](downstream-god-file-refactor.md). Every lane builder appends its own section here, in this repo (the desktop lane D1 too — it stands in this repo). The runtime-model skill is rewritten LAST from these notes, per the field-notes ruling.

## 0. The read that wrote the plan (Fable, 2026-09-21, read-only, `main` @ `f1268bd017`)

How every number in the plan's §0 was taken, so the next reader can re-take it without this session:

- **The counter and the per-file survey:** `scripts/refactor_census.py <files.txt> <out.json>` (landed with the plan). It prints three counters per file (raw / non-blank-non-comment / also-minus-docstrings); the middle one reproduces the operator's table exactly and is the gate's instrument. Per file it also lists the three biggest top-level units, the nested-function count inside the biggest, production importers, test files naming the module, and patch sites.
- **The fence:** `git ls-tree -r --name-only upstream/main` against `HEAD`'s listing — 1,439 fork-only files (962 `.py`); 3,625 upstream files modified by the fork. All 41 are fork-only. `upstream` was fetched at `ea0c2b820b`.
- **The 41-over-800 list** was recomputed from the fence, not copied from the operator's table: same 41 production files; 38 test files are also over and are out of scope by rule 1.6.
- **The exec loader:** `_load_command_parts` in `hermes_cli/harness.py`; the 263 patch sites were classified by AST (67 defined in harness.py, 155 imported into it, 41 defined in `persona_commands.py`); cross-part name collisions among harness.py + the seven parts: **0**.
- **`serve_loop`'s closure shape:** 39 nested functions; `_handle_message` reads 21 enclosing locals; 4 `nonlocal` statements — by AST walk, listed in the plan's H4 row.
- **The dead-code census** counts identifier TOKENS across every `.py` in the repo (strings included, so a decorator- or string-registered name is a reference). Result: 0 unreferenced top-level names in the 41 files; 12 test-only rows (plan §4.1). **Struck as false positives:** the 16 `serve_rpc.py` rows the census printed as unreferenced (`_runtime_office_{unsubscribe,remove,surface_update,resolve_conflict}`, `_runtime_persona_instance_open_chat`, `_runtime_persona_prewarm`, `_runtime_chat_steer`, `_runtime_realm_use`, `_runtime_media_index`, `_peer_{ping,agent_chat_execute,announce,roster_list,thread_read}`, `_runtime_gateway_peers_{list,roster}`) are registered through the `method()` decorator into `_METHODS`, so their NAME never appears again while their verb does. The census counts names; the registry keys verbs. The reach census (W0-D) is the instrument that can see them.
- **The duplicate census** is the existing gate's normalization (docstring stripped, own name normalized, `ast.unparse`, sha1) run over functions, methods and nested functions ≥ 4 unparsed lines across `agent_runtime/`, `hermes_cli/`, `tools/`, `agent/charsheet/`: 20 exact groups, of which the downstream-side rows are plan §5; the rest are upstream pairs. The same-name census (private helpers defined in ≥ 3 files) found 191 names repo-wide; the downstream ones with real overlap are in §5, the rest are ordinary local names (`_run` in 42 files is not one function).
- **Not run:** no coverage pass (that is W0-D), no test suite, no serve, nothing written outside `docs/` and `scripts/`.

## 1. Open at plan time

- The reach census (W0-D) — the §4.3 half of the delete list does not exist until it runs.
- The widened duplicate census (W0-G3, alpha-renamed) — §5 lists exact matches only; the near-duplicates (the board/office adoption shape, the six `_read_json`, the nine `_safe_text`) are sized by that census.
- The §4.2 argv census — which verbs the launcher still lowers to argv is a launcher-side read.

## 2. Lane sections (appended by builders)

<!-- W0 / H1 / S1 / H2 / H3 / R1 / R2 / R3 / R4 / C1 / T1 / D1 / H4 — one section each: worktree + branch + base SHA, the layout sheet, the source-pin census output, the patch-retarget script output, the sheet review, the positive control's red for the CHANGE commit, the [ds-size] line before/after, the commits. -->
