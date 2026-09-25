# Planned — downstream god-file refactor: every fork-owned production file under 800 code lines

**Status:** PLANNED 2026-09-21 (Fable, read-only against `main` at `f1268bd017`; every number in §0 was taken by the scripts named in the field notes and can be re-taken without this session). Not dispatched. Field notes: [`downstream-god-file-refactor-field-notes-2026-09-21.md`](downstream-god-file-refactor-field-notes-2026-09-21.md). **Owner docs:** [`../01-system-architecture.md`](../01-system-architecture.md) (the harness command surface and the exec-loaded parts), [`../03-transport-and-wire.md`](../03-transport-and-wire.md) (serve), [`../05-chat-turn-lane.md`](../05-chat-turn-lane.md) (the persona chat handlers). **Sibling program:** `EterniaLauncher/docs/mission_control/planned/mission-control-refactor-program.md` — the launcher ran this exact program first (2026-09-18 → 21); its four owner amendments are adopted here verbatim where they apply (§1), and where this plan departs from them it says so.

**Refreshed 2026-09-24:** [`god-file-program-2026-09-24.md`](god-file-program-2026-09-24.md) re-takes the numbers, adds rules 12–17 and gates W0-G5/G6/G7, and wins wherever the two disagree. Wave 0 instruments: `scripts/god_file_probe.py` (the population, every counter and every gate arm; `--check`) and `scripts/refactor_reach_census.py` (W0-D).

**The operator's brief (2026-09-21).** *Same as the launcher: code readability, every file under 800 code lines, enterprise grade. Create a dead-code delete list, collapse duplicate code, keep out of upstream. Big moves, few commits — not multiple paranoid little ones — but safely. Include all 41 files over 800.* And, the day before: *doing this one slowly so I can focus on the launcher* — so the plan is cut into lanes an Opus builder lands alone, in an order where nothing waits on the operator except the two field proofs §7 names.

**The headline, before the tables.** The 41 files are ALL fork-owned (none exists in `upstream/main`), so "keep out of upstream" is a fence to prove, not a constraint to design around. The by-name dead-code census over the 41 finds **zero** unreferenced top-level names — the 2026-08 dead-code audit and the tombstone waves already burned that layer — so the delete list (§4) is made of the three things a name census cannot see: production functions only tests call, the argv fallback lanes the R-W0/R-C4 rulings already marked for delete, and branches no test reaches (an instrument, W0-D, produces that half). The three biggest files are not three problems: files 1 and 2 are one 11,376-line namespace (persona_commands is `exec`'d into harness.py's globals) and file 3 is one 3,760-line function. §2 is built around those two facts.

This note cites SYMBOLS and FILES, never line numbers: every lane moves lines.

---

## 0. Ground truth (2026-09-21, `main` @ `f1268bd017`)

### 0.1 The instrument

"Code lines" in the operator's table = non-blank lines not starting with `#` (docstrings COUNT). The census script reproduces the table exactly (persona_commands 6,271 / harness 5,105 / serve 4,041). That counter is the gate's instrument (W0-G1); the minus-docstrings variant reads 5,398 / 4,424 / 2,925 and is NOT used — a docstring is a reader's cost too.

### 0.2 The fence

`git ls-tree -r --name-only upstream/main` ∖ `HEAD` = **1,439 fork-only files, 962 of them `.py`**. All 41 are in that set. The fork has also MODIFIED 3,625 upstream files; none of them is in scope, and W0-G2 makes touching one from a refactor lane a red.

### 0.3 The 41, by lane (code lines; the biggest unit inside; what the tests hold on to)

| # | file | code | the unit that makes it big | test files | patch sites |
|--:|---|--:|---|--:|--:|
| 1 | `hermes_cli/harness_parts/persona_commands.py` | 6,271 | `_mission_chat_commit_turn` 1,590 · `_cmd_mission_chat_message` 692 · `_ChatProtocolV2Emitter` 429 · `_cmd_persona_instance_open_chat` 322 | 44 | 41 (via `harness.`) |
| 2 | `hermes_cli/harness.py` | 5,105 | `build_parser` 1,712 · `_cmd_skills_delete` 212 · `_cmd_doctor` 149 | 432 | 263 (67 own, 155 imported names, 41 part names) |
| 3 | `hermes_cli/harness_parts/serve.py` | 4,041 | `serve_loop` 3,760 = 39 closures; `_handle_message` 856 reads 21 enclosing locals + 4 `nonlocal` | 46 | 0 |
| 4 | `agent_runtime/persona_assignments.py` | 3,172 | `PersonaInstanceStore` 2,364 / 48 methods (`open_chat` 203, `update_profile` 174, `retire` 130) | 88 | 5 |
| 5 | `agent_runtime/realm_sync.py` | 3,135 | flat: `publish_realm_sync` 223, `pull_realm_sync` 220, `apply_skill_inbox_pull` 193; 115 defs | 42 | 8 |
| 6 | `agent_runtime/serve_rpc.py` | 2,958 | flat: 48 decorator-registered methods (`_runtime_office_upsert` 333, `_runtime_office_subscribe` 325) | 49 | 0 |
| 7 | `agent_runtime/prompt_observability.py` | 2,932 | `mission_chat_prompt_observability` 501, `snapshot_prompt_observability` 223; 98 defs | 34 | 6 |
| 8 | `agent_runtime/profile_runner.py` | 2,736 | `ProfileAgentRunner` 708 (`_execute_agent_run` 424), `WallBudgetCheckpoint` 152; 94 defs | 45 | 3 |
| 9 | `agent_runtime/core_cache.py` | 2,505 | flat: `build_input_fingerprint` 236, `write_back` 223; 85 defs | 21 | 35 |
| 10 | `agent_runtime/serve_socket.py` | 2,194 | three classes: `ServeSocketServer` 859, `ServeSocketClient` 432, `SocketOwnerLock` 430 | 42 | 9 |
| 11 | `agent/charsheet/pipeline.py` | 1,898 | `detect_mirrored_art` 504, `validate_sheet` 265, `mirrored_art_error` 202 | 1 (2,211 lines) | 14 |
| 12 | `agent_runtime/office_store.py` | 1,874 | `OfficeStore` 1,780 / 35 methods (`upsert_actor` 249, `resolve_conflict` 136) | 62 | 0 |
| 13 | `agent_runtime/persona_chat_history.py` | 1,753 | `persona_chat_history_summary` 270, `_safe_curated_messages` 251 | 32 | 2 |
| 14 | `agent_runtime/snapshot.py` | 1,752 | `_parity_envelope` 338, `_build_snapshot_in_runtime_scope` 334, `_parity_warnings` 284 | 53 | 8 |
| 15 | `agent_runtime/persona_chat_continuity.py` | 1,646 | `PersonaChatClarifyTicketStore` 697, `PersonaChatMintReceiptStore` 237, `PersonaChatRuntimeRegistry` 163 | 19 | 0 |
| 16 | `hermes_cli/harness_parts/gateway_commands.py` | 1,645 | `cmd_gateway_peers_join` 443, `cmd_gateway_introduce` 266 | 10 | 22 |
| 17 | `agent_runtime/gateway_peers.py` | 1,621 | flat: `dial_peer` 172, `redeem_peer_code` 144; 43 defs | 18 | 12 |
| 18 | `agent/charsheet/draft.py` | 1,599 | `CharacterDraft` 1,335 / 42 methods (`compose` 151, `row_thumb` 139, `add_state` 103) | 6 | 0 |
| 19 | `agent_runtime/running_work.py` | 1,517 | `_collect_delegations` 233, `_collect_dispatches` 196, `_collect_terminal` 185 | 21 | 24 |
| 20 | `agent_runtime/mcp_admission.py` | 1,452 | `admit_mcp_servers` 198, `resolve_mcp_admission` 157, `McpCallBudget` 119 | 20 | 8 |
| 21 | `agent_runtime/agent_create.py` | 1,439 | `perform_agent_create` 691 | 41 | 4 |
| 22 | `tools/agent_chat_tool.py` | 1,430 | `agent_chat_send` 425 | 13 | 0 |
| 23 | `apps/desktop/src/app/skills/mcp-tab.tsx` | 1,398 | one component, 30 hook calls | (vitest) | — |
| 24 | `agent_runtime/operator_channels.py` | 1,394 | `_OperatorChannelBuilder` 254 | 18 | 0 |
| 25 | `agent_runtime/stream.py` | 1,385 | `stream_frames` 425 | 24 | 0 |
| 26 | `agent_runtime/dispatch_delivery.py` | 1,237 | `drain_background_completions` 240, `_DrainTelemetry` 176 | 18 | 21 |
| 27 | `agent_runtime/mission_chat_turns.py` | 1,156 | flat, 48 defs, biggest 84 | 29 | 11 |
| 28 | `agent_runtime/runtime_hud.py` | 1,103 | `render_situational_hud_block` 146 | 21 | 1 |
| 29 | `agent_runtime/state_patches.py` | 1,023 | flat, 27 defs, biggest 82 | 27 | 0 |
| 30 | `agent_runtime/dispatch_store.py` | 1,019 | `record_completion` 155 | 14 | 16 |
| 31 | `agent_runtime/persona_instance_sync.py` | 975 | `apply_persona_instance_pull` 273 | 5 | 1 |
| 32 | `agent_runtime/terminal_envelope.py` | 963 | `envelope_decision` 141 | 12 | 2 |
| 33 | `agent_runtime/board_store.py` | 925 | `BoardStore` 899 / 37 methods (`_idempotent_replay` 88, `adopt_remote_board` 83) | 16 | 0 |
| 34 | `apps/desktop/src/app/skills/index.tsx` | 916 | one component, 31 hook calls | (vitest) | — |
| 35 | `agent_runtime/store.py` | 911 | `RealmStore` 313, `WorkspaceStore` 284 | 114 | 16 |
| 36 | `agent_runtime/config.py` | 902 | flat, 43 defs, biggest 72 | 60 | 16 |
| 37 | `agent_runtime/chat_live_log.py` | 849 | flat, 38 defs | 11 | 14 |
| 38 | `agent_runtime/persona_profile_binding.py` | 847 | `rebind_persona_profile` 215, `backfill_instance_profile_ids` 138 (test-only) | 6 | 0 |
| 39 | `tools/agent_chat_dispatch.py` | 842 | `_run_remote_dispatch` 258 | 14 | 10 |
| 40 | `agent_runtime/harness_doctor.py` | 831 | `_placement_census_report` 255 | 8 | 3 |
| 41 | `scripts/changed_line_mutation_check.py` | 827 | `run` 173 | 9 | 0 |

"Patch sites" = `monkeypatch.setattr(<module>, "name")` + `patch("<module>.name")` occurrences across `tests/`. The `serve.py` "test files" figure and harness.py's 432 are substring-inflated by the census regex (`serve`, `harness`); the patch-site figures are exact.

Out of scope by ruling, named so nobody asks: **38 downstream TEST files are also over 800** (`tests/agent_runtime/test_persona_assignments.py` 4,289, `test_tombstone_registry.py` 3,825, `test_serve_socket_lane.py` 2,393 …). The launcher's program measured `lib/` only; this one measures production files only. A test file splits when its production file splits (rule 1.6), never as its own lane.

### 0.4 What the tests hold, and the trap inside it

`_load_command_parts` in `hermes_cli/harness.py` reads seven part files (`persona_commands`, `runtime_commands`, `board`, `office`, `level`, `flow_commands`, `checkpoint_commands`) and runs each with `exec(compile(...), globals())`. So every name in every part resolves through harness.py's global dict, and **263 test patches on `harness.<name>` work only because of that**: 67 name things harness.py defines, 155 name things harness.py merely imports (`load_agent_runtime_config` ×65, `_default_persona_session_db` ×42, `GPTPersonaRuntime` ×28, `_resolve_active_provider_id` ×25 …), 41 name things persona_commands defines (`_cmd_mission_chat_message` ×23 …). The moment a part becomes a real module, code inside it resolves names in ITS globals, and a patch on `harness.X` becomes a no-op that passes. `monkeypatch.setattr` raises on a MISSING attribute (its default `raising=True`) but not on a present-but-unused one — which is exactly what a re-export shim would leave behind. W0-G4 closes that door by construction (§2 Wave 0).

Verified today: **0 names are defined in more than one exec'd unit** (harness.py + the seven parts), so the conversion has no hidden override to unwind. `serve.py` is already a real module (its own comment in harness.py says why: it owns the stdout swap and is imported by tests) — it is the pattern the other seven should have followed.

Production imports from `hermes_cli.harness`, the whole list: `build_parser` (3 sites, one aliased `build_harness_parser`), `emit_harness_error` (2), `_cmd_characters_{list,status,sprite,thumb}` (1 each). That is the allowlist W0-G4 carries.

### 0.5 Existing gates this plan extends rather than duplicates

- `tests/agent_runtime/test_duplicate_helper_bodies.py` — hashes docstring-stripped, name-normalized `ast.unparse` renderings of MODULE-LEVEL functions in `agent_runtime/` only; `_GRANDFATHERED` holds the survivors. Widened by W0-G3 (all downstream `.py`, methods and nested functions too, alpha-renamed locals).
- `tests/fixtures/hermes_cli_contract.json` + `tests/hermes_cli/test_cli_contract_dump.py` — the parser surface as a fixture. The H2 lane's proof that a parser split changed nothing is this fixture being byte-identical.
- `tests/agent_runtime/test_tombstone_registry.py` — the tombstone ledger; a deletion from §4 lands with its tombstone row exactly as the 2026-08 waves did.
- `scripts/changed_line_mutation_check.py` (file 41 itself) — the changed-line mutation gate; every new gate in Wave 0 records its killing mutation through it.
- The CI runner (`.github/workflows/tests-os.yml`) runs one plain `pytest` per OS and fails a lane that selects zero tests — a moved test file that stops being collected is a red, not a silence.

---

## 1. The rules (adopted from the launcher program, with three departures)

1. **The 800-code-line ceiling is FLAT.** No exceptions list, no "one thing, not too long" tier (launcher amendment 2026-09-20 evening, reason of record: this code is read and edited mostly by agents, whose cost scales with file size twice — a whole-file read to change one method, and every lane that touches a big file collides with every other). **Split to a layout, never shave**: when a lane opens a file it answers "what lives here?" once, names the target modules by responsibility, and moves everything to its home in one pass. Landing at 790 by moving the smallest thing out is refused at review.
2. **The grain.** Target modules are named by responsibility, one of: *models and value types* · *pure policy and resolvers* (no I/O) · *stores and I/O* · *lanes and handlers* (one verb family per file) · *wiring, registration and probes*. A module opens with a docstring that says what lives there and WHY it is separate, declares `__all__`, and never does `from x import *`. No new module at the top level of `hermes_cli/` or `tools/` (those directories are upstream's); new code goes under `agent_runtime/`, `hermes_cli/harness_parts/`, `agent/charsheet/`, a new `tools/agent_chat/` package, `scripts/mutation_check/`, or `apps/desktop/src/app/skills/`.
3. **MOVE and CHANGE never share a commit.** A MOVE commit carries the moved text byte-for-byte plus imports, `__all__`, promoted names with their call sites, retargeted test patch paths and source-pin paths, and doc cite re-anchors — nothing else. A CHANGE commit (a closure becoming a class, a duplicate folding into one authority, a deletion from §4) is separate, reviewed, and lands with a positive control (the change tried on a throwaway copy, its red pasted into the message, reverted).
4. **Bulk mode — "big moves, few commits".** Per lane: **ONE MOVE commit** carrying every move the lane's layout names, **ONE CHANGE commit** carrying the lane's changes, and **at most one `style:` commit** (formatting the new modules AFTER their grandfather rows are deleted, never before — a formatter grows a file). No per-span receipts, no reconstruction proofs (the launcher measured them over a whole wave: they caught nothing the applied controls and the CHANGE review did not). *Departure 1 from the launcher's original §3.7: adopted its 2026-09-21 amendment, not its Wave 2 ceremony.*
5. **Promotion only with an outside caller.** A private name becomes public only when a production module outside its new home calls it; tests are not a caller. A moved private helper keeps its underscore.
6. **Tests move with their code.** When a production file splits, the test file that names it in `monkeypatch.setattr`/`patch` is retargeted in the MOVE commit (rule 3), and a test file over 800 that tests a file being split is split along the same seams in the same MOVE commit. Source-pin census first (launcher §3.6): every hit for the file's repo path or basename as a STRING across `tests/` and `scripts/` is retargeted or, for an absence gate, retargeted AND re-proved.
7. **Comments: keep WHY, relocate history.** A comment that explains an invariant, a trap or a ruling moves with its code verbatim. A comment that narrates what the code used to be moves to `docs/agent-runtime-harness/history/<surface>.md` — only in a CHANGE commit that rewrites that code, never as a sweep.
8. **A guard, an error state or a designed empty state is not bloat.** LOC is not the objective (the launcher retired its 30 % target on 2026-09-20 with numbers: decomposition RAISES the total by construction). The objectives are: grandfathered units **41 → 0**, one authority per helper (§5), and the §4 deletions with their tombstones.
9. **Keep out of upstream — mechanically.** W0-G2 reds any refactor commit that touches a file present in `upstream/main`. A duplicate whose second copy lives in an upstream file (§5 lists them) is folded on the DOWNSTREAM side only; the upstream copy is left alone and named in the baseline with `upstream_copy_left` as its reason. *Departure 2: the launcher had no upstream; this rule is new.*
10. **Nothing waits on the operator except §7.** Design questions inside a lane are answered by the lane's layout sheet and reviewed by a separate Opus agent before the MOVE commit; that review replaces owner sign-off. *Departure 3: the launcher's per-file design notes were retired for layout sheets on 2026-09-20 late; this plan starts there — one sheet per lane, §2 already carries the layout for every file, so a sheet is a confirmation against the tree, not a design from scratch.*
11. **Landing protocol** (§6) — full suite green on the rebased tree, no baselining, the G1 row rides the commit that crosses 800, push after every commit, one worktree per lane cut from a neutral cwd, never a checkout switch in the primary.

---

## 2. Stages

### Wave 0 — the gates (one lane, ONE commit, before any move)

Nothing in Wave 1+ lands before this commit is on `main`. Each gate lands with its killing mutation recorded through `scripts/changed_line_mutation_check.py`.

| id | gate | what it asserts | baseline it carries | red proof owed |
|---|---|---|---|---|
| **W0-G1** | `tests/tooling/test_downstream_size_ceiling.py` | every fork-only production `.py`/`.tsx`/`.ts` file (the §0.2 set, recomputed from a committed manifest `tests/fixtures/downstream_manifest.txt` — CI has no `upstream` remote) is ≤ 800 code lines by the §0.1 counter, OR is listed in `tests/fixtures/size_ceiling_grandfathered.json` with its count; a listed file that GREW reds; a listed file now under 800 reds until its row is deleted ("the list only shrinks"); the manifest is regenerated by `scripts/downstream_manifest.py` and a stale manifest reds | the 41 rows of §0.3 | (a) add 1 line to a listed file → GREW red; (b) a new 801-line file → red; (c) delete a row for a file still over → red; (d) counter mutation (count comments) → the fixture disagrees → red |
| **W0-G2** | `tests/tooling/test_refactor_stays_downstream.py` | for every commit on `main` whose subject starts with `refactor(` since the Wave 0 landing SHA, `git diff-tree --name-only` ∩ upstream manifest = ∅. Reads `tests/fixtures/upstream_manifest.txt` (the `git ls-tree upstream/main` listing at the Wave 0 SHA, regenerated by the same script) | none | a throwaway `refactor(x):` commit touching `hermes_cli/main.py` → red |
| **W0-G3** | widen `test_duplicate_helper_bodies.py` | scope: all downstream `.py`; units: module-level functions, methods, nested functions ≥ 4 unparsed lines; normalization adds alpha-renaming of locals and parameters (positional `_v0`, `_v1`) so a renamed-variable clone collides; `_GRANDFATHERED` re-baselined from the widened census and only shrinks | the §5 rows + whatever the widened census finds (the builder pastes the count into the commit) | copy any 5-line helper into a second module under a new name → red |
| **W0-G4** | `tests/tooling/test_harness_namespace_is_thin.py` | `hermes_cli.harness` binds NO callable defined in another module except the §0.4 allowlist (`build_parser`, `emit_harness_error`, `_cmd_characters_{list,status,sprite,thumb}`) and the argparse `func=` targets referenced through their part modules; `_load_command_parts` and every `exec(` in `hermes_cli/` are absent | none — but it is RED on today's tree by construction (see H1); it lands in the Wave 0 commit marked `xfail(strict=True)` and H1's CHANGE commit flips it | re-add one `from .harness_parts.persona_commands import _cmd_persona_list` to harness.py → red |
| **W0-D** | `scripts/refactor_reach_census.py` + `docs/agent-runtime-harness/planned/downstream-god-file-refactor-reach-census.md` | ONE run of the suite under `coverage` (already a dev dep, `coverage==7.16.0`) restricted to the 41 files, then a listing of every function/method ≥ 10 lines and every branch arm ≥ 10 lines with **zero** hits. This is the second half of the §4 delete list. **0 hits ≠ dead**: field-only paths (Windows-only, service-mode, peer-only) are expected here; each row gets a named reason before it is a deletion (§4.3) | none | none (an instrument, not a gate) |

Commit: `test(tooling): W0 — downstream size ceiling, upstream fence, widened duplicate gate, thin harness namespace (xfail), reach census`. The G1 ledger line the gate prints (`[ds-size] units=41 total=<n> ceiling=800`) is quoted in the message.

### Wave 1 — H1: the seven exec'd parts become modules (the one lane every harness lane waits on)

**Lane H1** · files: `hermes_cli/harness.py`, the seven parts · 2 commits.

- **MOVE (none).** Nothing moves in H1. Its first commit is a CHANGE.
- **CHANGE 1 — `refactor(harness): the seven command parts are modules, not exec'd text`.**
  - Delete `_load_command_parts` and the `exec`. Each part gets `from __future__ import annotations`, its own imports (derived from the part's free identifiers, never by subtraction), and `__all__`.
  - Helpers the parts reached through harness.py's globals (`emit_harness_error`, `_default_persona_session_db`, `_persona_by_id`, `load_agent_runtime_config` re-imports, the `_usage_lane_detected` family, `GPTPersonaRuntime` …) move to a leaf `hermes_cli/harness_parts/_common.py` (stdlib + `agent_runtime` imports only, no import of `hermes_cli.harness` — so no cycle). harness.py imports them from there too. A part never imports `hermes_cli.harness`; `serve.py`'s two lazy imports of it (`build_parser`, `emit_harness_error`) are repointed to `_common` and the parser module H2 creates.
  - `build_parser`'s `set_defaults(func=…)` sites reference the part modules' names (`persona_commands._cmd_persona_list`), so the parser is unchanged as a SURFACE — `tests/fixtures/hermes_cli_contract.json` must be byte-identical (the H1 proof).
  - **The 196 patch retargets**, by script (`scripts/retarget_harness_patches.py`, kept in the repo): for every `monkeypatch.setattr(harness, "N")` / `patch("hermes_cli.harness.N")` in a test file, if exactly one of {harness.py, `_common`, the seven parts} BINDS `N` after the conversion, rewrite the target to that module; if more than one binds it (a name imported into several parts), rewrite to the module that defines the handler the test file exercises (the test's `func=`/`_cmd_` call), and list the remainder for the builder by hand. The script's output (rewritten / by-hand / untouched) is pasted into the commit message.
  - Flip W0-G4 from `xfail(strict=True)` to a plain test in this commit — the gate that makes a silent no-op patch impossible from here on.
- **CHANGE 2 — `refactor(harness): argv fallback lanes marked for delete are deleted`** — the §4.2 rows that live in harness.py / persona_commands (the argv paths the R-C4 manifest lane superseded), with their tombstones. Lands only if §4.2's grep census (run by the H1 builder first) proves no caller; otherwise the rows go back to §4.2 with the caller named.

Gate: full suite; contract fixture byte-identical; W0-G4 green; `[ds-size]` unchanged (41 — H1 shrinks nothing, by design).

### Wave 2 — the parallel lanes (any order, any parallelism the box allows; each lane = one worktree, one builder)

Each row is one lane: **one MOVE commit, one CHANGE commit (if the row names a change), one `style:` commit at most.** "Layout" is the target module set; the builder confirms it against the tree, and where the tree disagrees the tree wins and the commit message says so. Sizes are today's, so a builder can see the layout lands every module well under 800 — a module the layout would put at 700+ is split further at the sheet, not at the landing.

#### H2 — harness.py (waits on H1)

| target | what moves there | ~code |
|---|---|---|
| `hermes_cli/harness_parts/parser/__init__.py` | `build_parser` becomes a table: `PARSER_FAMILIES: tuple[Callable[[subparsers], None], ...]` and a 30-line `build_parser` that iterates it; `_add_stage42_global_args`, `_add_coordinator_permission_args` | 150 |
| `parser/{roots,gateway,skills,workspace,realm,persona,chat,characters,doctor,serve,office_board_level}.py` | one `add_<family>_parser(sub)` per family, cut from `build_parser` at its existing `# ---` family boundaries; each ≤ 250 | 1,700 total |
| `harness_parts/roots_commands.py` | `_cmd_roots_*`, `_machine_root_config_paths`, `_cmd_roots_migrate` | 150 |
| `harness_parts/gateway_identity_commands.py` | `_gateway_install_row`, `_gateway_identity_error`, `_cmd_gateway_id`, `_cmd_gateway_rename`; the eight `_cmd_gateway_*` one-line trampolines DELETE (parser `func=` points at `gateway_commands.cmd_*` directly) | 200 |
| `harness_parts/skills_commands.py` + `skills_promotion_commands.py` | `_cmd_skills_{catalog,publishable,inbox}`; promote/delete/restore with `_resolve_promotion_source`, `_canonical_packages_covered`, `_realm_publishes_skill`, `_prune_inbox_packages`, `_archive_content_hint` | 250 + 450 |
| `harness_parts/workspace_commands.py`, `realm_commands.py` | the `_cmd_workspace_*` / `_cmd_realm_*` families with their helpers | 300 / 350 |
| `harness_parts/characters_commands.py` | `_cmd_characters_*` and `_pet_sheet_revision` (the §5 duplicate — folded in this lane's CHANGE) | 500 |
| `harness_parts/doctor_commands.py`, `prompt_context_commands.py` | `_cmd_doctor` (149) and `build_provider_visibility`; `_cmd_prompt_context_show` | 250 |
| `hermes_cli/harness.py` (head) | `harness_command`, `emit_harness_error` (or its `_common` re-export per the allowlist), `_cmd_serve`/`_cmd_serve_connect` trampolines, the family imports | ≤ 150 |

CHANGE: the routing-as-data parser table; the eight trampolines deleted; `_pet_sheet_revision` folded into `agent/charsheet/revisions.py`. Proof: contract fixture byte-identical; `[ds-size]` 41 → 40.

#### H3 — persona_commands.py (waits on H1; the chat lane's owner doc is 05)

| target | what moves there | ~code |
|---|---|---|
| `harness_parts/persona_commands.py` (head) | `_cmd_persona_{list,show,tool_diff,permission_set,assignments,assignment_task_id_migration}`, `_persona_chat_fault_injection` | 400 |
| `harness_parts/agent_lifecycle_commands.py` | `_cli_create_persona`, `_cmd_agent_create`, `_console_denial`, `_agent_retire_outcome`, `_cmd_agent_retire`, `_placement_discriminability_refusal`, `_cmd_persona_instance_create` | 600 |
| `harness_parts/persona_chat_open.py` | `_cmd_persona_instance_open_chat`, `_cmd_persona_instance_open_new_chat`, `_persona_instance_updated_at`, `_prewarm_chat_actor_for_open`, `_emit_persona_open_chat_{payload,error}` | 650 |
| `harness_parts/persona_chat_delete.py` | `_cmd_persona_chat_delete`, `_retired_persona_instance_{payload,refusal}` | 350 |
| `harness_parts/chat_coordinator.py` | `_coordinator_actor_id`, `_coordinator_scope_from_args`, `_coordinator_confirm_payload`, `_maybe_stamp_spawned_by`, `_cmd_mission_chat_steer`, `_cmd_mission_chat_queue_skill` | 350 |
| `harness_parts/chat_events.py` | `_publish_persona_chat_{projection,metadata,send_refused}_event`, `_mission_chat_emit`, `_ChatProtocolV2Emitter` (429) | 700 |
| `harness_parts/chat_admission.py` | `_mission_chat_busy_outcome` (198), `_bind_mission_chat_delivery_capability`, `_mission_chat_lease_provenance`, `_normalize_deferred_thread_policy`, `_within_admitted_turn`, `_registry_probe_rounds`, the visibility-bundle cursor/rebuild helpers, `_turn_skill_resolver`, `_safe_pre_admit_timings`, `_prewarm_constructions_overlapped`, `_snapshot_builds_overlapped` | 650 |
| `harness_parts/chat_turn_message.py` | `_cmd_mission_chat_message` (692) | 700 |
| `harness_parts/chat_turn_commit.py` | `_mission_chat_commit_turn` (1,590) — MOVED whole in the MOVE commit, then… | 1,600 → |
| …`chat_turn_commit/{admit,prepare,run,finalize,emit}.py` | …in the CHANGE commit `_mission_chat_commit_turn` becomes a `TurnCommit` object with one method per phase the ledger already names (`anchored`, `write_ahead`, `agent_ready`, `request_assembled`, `finalized` — the §0 marks of `chat-turn-prep-cost.md`), each phase ≤ 300 lines, its six nested helpers becoming methods; `_stamp_turn_visibility`, `_stamp_reply_media` go to `finalize` | 5 × ≤ 350 |

CHANGE proof: the per-turn ledger record for a fixture turn is byte-identical before and after (the `mission_chat_turns` v3 record is the behaviour contract); RB-7/RO-9 unaffected (this lane does not touch serve). `[ds-size]` 40 → 39.

#### H4 — serve.py (LAST of the harness lanes; waits on H1–H3 landing so nothing else is moving in the boot path)

MOVE: `harness_parts/serve.py` → package `harness_parts/serve/`:

| target | what moves there | ~code |
|---|---|---|
| `serve/manifest.py` | `ops_manifest`, `_pairing_block`, `_is_gateway`, `_credential_kind` | 250 |
| `serve/gateway_listener.py` | `gateway_listen_config`, `gateway_block_when_no_listener`, `start_gateway_listener`, `_gateway_authenticator` | 450 |
| `serve/end_reason.py` | `_ServeEndReason`, the console-ctrl/signal reason handlers, `_install_service_stop_signal`/`_restore_…`, `_end_reason_is_known` | 350 |
| `serve/boot.py` | `_maybe_inject_boot_fault`, `_runtime_state_fingerprint` + the two `_stat_*` walkers, the three `_prewarm_*`, `install_harness_skills_at_boot`, `_annotate_import_tax`, `_repoint_logging_root_stderr` | 550 |
| `serve/frames.py` | `_PollResponseCache{,Entry}`, `current_serve_request_id`, `_FrameWriter`, `_LineFrameProxy`, `_SafeSink`, `_emit_deferred_reply` | 450 |
| `serve/argv_lane.py` | `_ArgvRequest`, `HandlerExit`, `ArgvRootUnsupported`, `_build_harness_parser`, `_system_exit_code`, `_clean_argv_root`, `dispatch_argv` | 300 (shrinks in §4.2) |
| `serve/drain.py` | `_DrainState`, `_drain_deadline_seconds`, and the `_drain_monitor` / `_finish_drain` closures once they are methods | 350 |
| `serve/loop.py` | `serve_loop` — moved WHOLE in the MOVE commit (3,760, grandfathered for exactly one commit) | |
| `serve/__init__.py` | `_cmd_serve`, `_cmd_serve_connect`, `_raw_fd_lines`, `_claim_protocol_pipes`, re-exports of the names the 46 test files import from `hermes_cli.harness_parts.serve` (the ONE place a re-export is allowed, because the tests name this module by path; W0-G4 does not cover it — the CHANGE commit retargets the tests and deletes the re-exports) | 400 |

CHANGE: `serve_loop` becomes `class ServeSession` in `serve/session.py` whose fields are the 21 enclosing locals `_handle_message` reads (`auth_block`, `boot_id`, `frames`, `gateway_block`, `gateway_server`, `inflight`, `inflight_futures`, `inflight_lock`, `install_block`, `lane_lock`, `liveness_stop`, `pool`, `runtime_root`, `sink`, `socket_block`, `socket_lock`, `socket_server`, `starter_pid`, `stream_fold_entities`, `stream_hub`, plus the 4 `nonlocal`s as fields); the 39 closures become methods grouped into `serve/{session,handle_message,lanes,drain}.py` (`_handle_message` 856 → a dispatch table keyed by frame kind, one method per kind); `serve_loop(...)` survives as a 20-line function that builds the session and runs it, so every caller and the two field tools (`mission_runtime_timeline`, the RO-1 sidecar) see the same entry point. Proof: RB-7 and RO-9 green both arms, the boot timeline line byte-identical for a fixture boot, the `ready` frame byte-identical, and **§7's operator boot**. `[ds-size]` → −1.

#### R1 — agent_runtime stores

| file | layout | change |
|---|---|---|
| `persona_assignments.py` (4) | `persona_instances/{store,steering,retire,chat_binding,repair,replicate}.py` — `PersonaInstanceStore` keeps `get/scan_all/list_all/ensure_for_persona(s)/add_instance/update/_write/_event` (~450); steering (`steer`, parents, `_apply_steer_edges`, `_commit_steer`, `_validate_no_steering_cycle`, `apply_replicated_steering`) → a `SteeringLane(store)` collaborator; retire (`retire`, receipts, `_archive_*`, `retired_*`) → `RetireLane`; chat binding (`open_chat` 203, `rollback_chat_root_bind`, `create_operator_chat`, `assert_bindable`, `_session_owned_by_other_instance`, `clear_chat_session_binding`) → `ChatBindingLane`; the two `repair_*` + `repair_missing_chat_session_bindings` → `repair.py`; `replicate_instance`/`retire_replica`/`_replica_row` → `replicate.py`; `PersonaAssignmentStore` + `persona_instance_summary` → `assignments.py` | composition, not mixins: each lane takes the store and calls its `_write`/`_event`; the store's public methods that a lane owns become one-line delegations so every caller is unchanged. `tests/agent_runtime/test_persona_assignments.py` (4,289) splits along the same six seams in the MOVE commit (rule 1.6) |
| `office_store.py` (12) | `office/{store,actor_writes,adoption,conflicts,archive,patches}.py` — `_emit_*_patch` (5 methods, 260) → `patches.py`; `upsert_actor` 249 + `remove_actor` + `restore_actor` + the four `_guard_*` → `actor_writes.py`; `adopt_remote_{surface,actor}` → `adoption.py`; `scan_conflicts` + `resolve_conflict` 136 → `conflicts.py`; `archive_*`/`archived_*` → `archive.py` | the §5 conflict-adoption fold with `board_store` lands here (CHANGE) |
| `board_store.py` (33) | `board/{store,cards,ordering,adoption,idempotency}.py` | `_guard_no_conflict`, `_emit`, adopt/resolve shape → the same `store_conflicts.py` authority R1 creates for office |
| `store.py` (35) | `realm_store.py` (313) + `workspace_store.py` (284) + `store.py` (the shared base, `_emit_active_scope_patch`) | — |
| `dispatch_store.py` (30) | `dispatch/{store,completion,restore}.py` | `_emit` → the shared store-event helper |
| `persona_chat_continuity.py` (15) | `persona_chat/{clarify_tickets,mint_receipts,runtime_registry}.py` | `_try_lock`/`_unlock` → §5 fold into `agent_runtime/file_locks.py` |

#### R2 — agent_runtime chat lane (owner doc 05)

| file | layout | change |
|---|---|---|
| `prompt_observability.py` (7) | `prompt_observability/{mission_chat,snapshot,skills,available_skills,resolver}.py` — `mission_chat_prompt_observability` 501 → a builder object with one method per section of the row it writes | the three skill walkers named in `chat-turn-prep-cost.md` §0.3 stay where Stage 8 put them; this lane does not touch their behaviour |
| `persona_chat_history.py` (13) | `persona_chat/history/{summary,curation,messages,revisions}.py` | `_safe_trace_int` → serde (§5) |
| `mission_chat_turns.py` (27) | `mission_chat_turns/{records,vocabulary,persist,locks}.py` | `_lock_fd_exclusive_nonblocking`/`_unlock_fd` → `file_locks.py` (§5) |
| `chat_live_log.py` (37) | `chat_live_log/{writer,backfill,stats}.py` | `_exists` → `paths.py` (downstream side only; the `hermes_cli/gateway.py` copy is upstream — left, baselined `upstream_copy_left`) |
| `operator_channels.py` (24) | `operator_channels/{builder,history,tool_calls}.py` | — |
| `runtime_hud.py` (28) | `runtime_hud/{resolve,render,capability}.py` | `hud_field`/`volatile_hud_keys` → §4.1 decision |
| `terminal_envelope.py` (32) | `terminal_envelope/{decision,grants,models}.py` | — |
| `running_work.py` (19) | `running_work/{delegations,dispatches,terminal,collect}.py` (one `_collect_*` per file, the shared row shape in `collect.py`) | `_row` → one authority (§5) |
| `dispatch_delivery.py` (26) | `dispatch_delivery/{drain,telemetry,once}.py` | — |

#### R3 — agent_runtime serve, runtime and cache

| file | layout | change |
|---|---|---|
| `serve_rpc.py` (6) | `serve_rpc/{registry,office,persona,chat,peer,gateway,realm,media,discussion}.py` — the `_METHODS` dict, `method()` decorator and tiers stay in `registry.py`; each verb family registers itself on import from `serve_rpc/__init__.py` (explicit import list, so `list_methods()` is unchanged and `test_serve_rpc_*` see the same table) | — |
| `serve_socket.py` (10) | `serve_socket/{server,client,owner_lock,frames}.py` (three classes, three files; `_write_json_atomic` is already in serde) | — |
| `profile_runner.py` (8) | `profile_runner/{runner,request,budget,mcp_lane,execute}.py` — `_execute_agent_run` 424 → `execute.py` as a function object with one method per phase | `_positive_int`, `_safe_exit_code` → serde (§5) |
| `mcp_admission.py` (20) | `mcp_admission/{resolve,admit,budget,models}.py` | `_positive_int` → serde |
| `stream.py` (25) | `stream/{frames,scope,batches,defer}.py` (`_defer_demote_build_for_active_turns` and Stage 5's deferral live in `defer.py`, so the CP-9 wave's next stage has one file to open) | — |
| `snapshot.py` (14) | `snapshot/{build,parity,warnings,sections}.py` | — |
| `core_cache.py` (9) | `core_cache/{fingerprint,write_back,config_keys,read,census}.py` | `fingerprint_home_capture`, `iter_fingerprint_paths`, `BUILD_SELF_PERTURBED_CLASSES` → §4.1 decision |
| `state_patches.py` (29) | `state_patches/{build,persona_instance,office,delta}.py` | — |
| `config.py` (36) | `config/{load,authority,misplaced_keys,models}.py` | `_positive_int` → serde |
| `harness_doctor.py` (40) | `harness_doctor/{run,placement_census,root_config,report}.py` | `ORPHAN_ACTOR_REASONS` → §4.1 |

#### R4 — sync, gateway, create

| file | layout | change |
|---|---|---|
| `realm_sync.py` (5) | `realm_sync/{publish,pull,skill_inbox,git,status,models,errors}.py` | `_row`, `_add` → §5 |
| `gateway_peers.py` (17) | `gateway_peers/{dial,codes,roster,models}.py` | — |
| `harness_parts/gateway_commands.py` (16) | `harness_parts/gateway/{pair,introduce,peers_join,devices,dial_policy}.py` (`cmd_gateway_peers_join` 443 → `peers_join.py` as steps: redeem, dial, verify, persist) | — |
| `persona_instance_sync.py` (31) | `persona_instance_sync/{pull,project,summary}.py` | — |
| `persona_profile_binding.py` (38) | `persona_profile_binding/{rebind,artifacts}.py` | `backfill_instance_profile_ids` (138, test-only) → §4.1 |
| `agent_create.py` (21) | `agent_create/{perform,normalize,skills_phase,receipts}.py` — `perform_agent_create` 691 → phases | — |

#### C1 — charsheet

| file | layout | change |
|---|---|---|
| `agent/charsheet/pipeline.py` (11) | `charsheet/pipeline/{run,validate,mirrored_art,rgba}.py` (`detect_mirrored_art` 504 + `mirrored_art_error` 202 → `mirrored_art.py`) | `_open_rgba` → `palette._as_rgba` (§5) |
| `agent/charsheet/draft.py` (18) | `charsheet/draft/{draft,directions,rows,states,thumbs,compose,status,home}.py` — `CharacterDraft` keeps identity/stage/save (~300); directions (`run_turnaround`, `reroll_direction`, `approve_*`, `_face_offset`) → `directions.py`; `run_rows`/`reroll_row`/`_row_reference` → `rows.py`; `add_state` → `states.py`; `row_thumb`/`direction_thumb`/`_finish_thumb` → `thumbs.py`; `compose` → `compose.py`; `status_payload`/`_item_status` → `status.py`; `migrate_characters_home`, `record_home`, `hermes_home` → `home.py` | `_sheet_revision` is the surviving authority for `_pet_sheet_revision` (H2 folds toward it) |

`tests/agent/test_charsheet_{draft,pipeline}.py` (2,256 / 2,211) split along the same seams (rule 1.6).

#### T1 — tools

`tools/agent_chat_tool.py` (22) + `tools/agent_chat_dispatch.py` (39) → package `tools/agent_chat/{send,threads,dispatch,remote,guarded,argv}.py`; `tools/agent_chat_tool.py` and `tools/agent_chat_dispatch.py` remain as ≤ 40-line entry modules because the tool registry names them by path (source-pin census first). `_refusal` → one authority with the R4/H3 copies (§5).

#### S1 — scripts

`scripts/changed_line_mutation_check.py` (41) → `scripts/mutation_check/{claims,partition,run,report}.py` + a ≤ 60-line `scripts/changed_line_mutation_check.py` entry (its nine test files name the script by path). This lane lands FIRST in Wave 2 because every other lane's gate landing runs it.

#### D1 — desktop

`apps/desktop/src/app/skills/mcp-tab.tsx` (23) and `index.tsx` (34): each becomes a ≤ 150-line page component plus one file per named sub-component/hook (`mcp-tab/{server-list,server-editor,log-panel,use-mcp-servers}.tsx`, `skills/{skills-page,skills-toolbar,use-skills-page}.tsx`); the `.test.tsx` siblings move alongside. Gate: the desktop `eslint` + `vitest` run the repo already has, plus W0-G1 (which counts `.tsx`). No React behaviour change; `useStore`/`useQuery` call sites are moved, not rewritten.

### Wave 3 — burn-down

After every Wave 2 lane has landed: (1) `[ds-size] units=0` and the grandfather fixture is an empty list — the gate stays, the fixture stays empty; (2) W0-G3's `_GRANDFATHERED` has only `upstream_copy_left` rows; (3) the §4 delete list is either deleted-with-tombstone or carries a named reason per row in §4.4; (4) the field notes are closed and the harness skill's runtime-model doc (already over its 16,384-byte ceiling, unrowed since 09-03) is rewritten LAST from the notes, per the field-notes ruling.

---

## 3. Order and parallelism

```
W0 ──► H1 ──► H2 ──┐
              H3 ──┼──► H4 (last; §7 boot)
S1 ──► R1 · R2 · R3 · R4 · C1 · T1 · D1   (any order, any parallelism)
```

Hard orderings: **W0 before everything**; **H1 before H2/H3/H4**; **S1 before any other Wave 2 landing** (the gates run it); **H4 after H1–H3 have landed**. R1–R4, C1, T1, D1 are independent of each other and of the H lanes (they share no file). Lane collisions to watch: R1 and R3 both create `agent_runtime/file_locks.py` / touch `serde.py` — whichever lands second rebases onto the first's authority (rule 1.11), never re-creates it.

"Slowly, to focus on the launcher" means: W0 + S1 in one sitting (a day), H1 in its own sitting (it is the only lane with a real trap), then one lane whenever there is a builder to spare. Nothing in the order blocks the launcher's program; the two share no repo.

---

## 4. The dead-code delete list

### 4.1 Production functions only tests call (the by-name census, exact)

The rule: a production function no production code calls is either a **test seam** (then it moves to `tests/<pkg>/_seams.py` and is deleted from production) or **dead** (deleted with its tests and a tombstone). Both are deletions from production. Rows, with the recommendation the lane builder applies unless the sheet review overturns it:

| file | symbol | lines | recommendation |
|---|---|--:|---|
| `agent_runtime/persona_profile_binding.py` | `backfill_instance_profile_ids` | 138 | **delete** — a one-time migration whose field run is recorded in the debt ledger ([`../08-performance-and-debt-ledger.md`](../08-performance-and-debt-ledger.md)); tombstone with the ledger cite. If the R4 builder finds a `harness_doctor --fix` path reaches it by string, it is a caller and the row moves to §4.4 |
| `agent_runtime/persona_assignments.py` | `reset_unreadable_instance_rows` | 12 | test seam → `tests/agent_runtime/_seams.py` |
| `agent_runtime/profile_runner.py` | `reset_runtime_resolve_cache` | 5 | test seam |
| `agent_runtime/core_cache.py` | `fingerprint_home_capture` | 23 | test seam (the core-cache-home-capture-timing plan's instrument; keep as a seam, not production) |
| `agent_runtime/core_cache.py` | `iter_fingerprint_paths` | 5 | test seam |
| `agent_runtime/core_cache.py` | `BUILD_SELF_PERTURBED_CLASSES` | 5 | test seam |
| `agent_runtime/runtime_hud.py` | `hud_field`, `volatile_hud_keys` | 8 | test seam |
| `agent_runtime/store.py` | `active_workspace_lifts` | 4 | test seam |
| `agent_runtime/harness_doctor.py` | `ORPHAN_ACTOR_REASONS` | 5 | **keep** if the doctor's report cites its members by string (the census counts tokens, so a string cite would have shown; it did not) — otherwise test seam |
| `agent_runtime/mcp_admission.py` | `READ_ONLY_ALLOWLIST_PROFILE` | 1 | test seam |
| `agent_runtime/serve_rpc.py` | `_runtime_office_get` | 60 | **NOT dead** — decorator-registered (`@method("runtime.office.get")`); the census's 16 other serve_rpc "unreferenced" rows are the same false positive and are struck (field notes §1) |

### 4.2 The argv fallback lanes the rulings already marked for delete (a grep census the H1 builder runs, then deletes)

Standing ruling (`feedback_rpc_route_first`, 2026-09-05, cited as R-C4 in `remote-chat-parity.md`): *every touched write lane moves to the hermes method lane by manifest membership; argv = fallback marked for delete.* `serve_rpc.py`'s comment above the office verbs says the launcher's argv lowering for two of them "is marked for delete". The census: for every `_cmd_*` the argv lane (`_ArgvRequest` → `dispatch_argv` → `build_parser`) can reach, is there a manifest method (`_METHODS`) that carries the same verb AND does the launcher (`EterniaLauncher`, grep `args_not_carried` / the method-lane manifest) still lower it to argv? Rows where the answer is "method exists, launcher no longer lowers" are deletions: the `_cmd_*`, its parser family entry (the contract fixture CHANGES here — regenerated in the same commit with the two ADDED/REMOVED rows named, as `5531e5b6f4` did), its tests, a tombstone. Rows where the launcher still lowers stay and are listed in §4.4 with the launcher row that must land first. Expected size: the chat send/steer/new-chat argv paths (R-C8 moved them to the 18-key message) and the office upsert/remove argv paths. The `dispatch_argv` lane itself stays — the operator's own CLI is an argv caller.

### 4.3 Branches no test reaches (W0-D's reach census; the second half of the list)

W0-D lists every function/method ≥ 10 lines and branch arm ≥ 10 lines in the 41 files with zero hits under the full suite. The lane that owns the file rules each row into one of: **delete** (no field path either — deleted with tombstone in the lane's CHANGE commit), **field-only** (Windows/service/peer path; kept, and the row names the field proof that exercises it), **untested live code** (kept; a test is owed, rowed in the queue, NOT written in the refactor lane). The reach census is re-run at Wave 3 and the delete arm must be empty.

### 4.4 Kept with a named reason

Filled by the lanes. Every row: file, symbol, reason, and the thing that would have to change for it to become a deletion.

**H1's §4.2 census (2026-09-24): zero deletions.** Every argv verb with a method twin is still declared as an argv capability by the launcher, whose method lanes answer `null` = "let argv carry it" (`EterniaLauncher` `lib/features/mission_control/data/bridge/mission_action_method_lanes.dart`). Kept, each until the launcher row that retires its argv lowering lands:

| file | symbol | method twin | launcher argv caller |
|---|---|---|---|
| `hermes_cli/harness_parts/persona_commands.py` | `_cmd_mission_chat_message` | `runtime.chat.message` | `harness_persona_capabilities.dart` `['harness','mission-chat','message']` |
| `hermes_cli/harness_parts/persona_commands.py` | `_cmd_mission_chat_steer` | `runtime.chat.steer` | same file, `['harness','mission-chat','steer']` |
| `hermes_cli/harness_parts/office.py` | `_cmd_office_actor_upsert` / `_cmd_office_actor_remove` / `_cmd_office_set_folders` / `_cmd_office_resolve_conflict` | `runtime.office.{upsert,remove,surface.update,resolve_conflict}` | `harness_office_capabilities.dart` |
| `hermes_cli/harness_parts/persona_commands.py` | `_cmd_persona_instance_open_chat` | `runtime.persona.instance.open_chat` | `mission_open_chat_lowering.dart` (argv fall-through) |

---

## 5. The duplicate collapse list (downstream side; exact-body census, ≥ 4 lines)

| survivor (authority) | copies folded | lane |
|---|---|---|
| `agent_runtime/serde.py::positive_int` | `_positive_int` in `mcp_admission.py`, `profile_runner.py`, `config.py` (byte-identical pairs; config's differs by a default and is unified with a parameter) | R3 |
| `agent_runtime/file_locks.py` (new leaf: `try_lock_exclusive(fd)`, `unlock(fd)`) | `mission_chat_turns._lock_fd_exclusive_nonblocking`/`_unlock_fd` ≡ `persona_chat_continuity._try_lock`/`_unlock` (both 8-line bodies identical) | R2 (creates), R1 (folds) |
| `agent_runtime/serde.py::safe_int` | `persona_chat_history._safe_trace_int` ≡ `profile_runner._safe_exit_code` | R2/R3 |
| `agent/charsheet/revisions.py` | `draft._sheet_revision` ≡ `harness._pet_sheet_revision` | H2 → C1's authority |
| `agent/charsheet/palette.py::_as_rgba` | `pipeline._open_rgba` | C1 |
| `agent_runtime/paths.py::path_exists_safe` | `chat_live_log._exists` (the second copy `hermes_cli/gateway.py::_path_exists_safe` is UPSTREAM — left, baselined `upstream_copy_left`) | R2 |
| `agent_runtime/serde.py::read_json` | `_read_json` in `board_store`, `office_store`, `store`, `mission_chat_steer`, `runtime_instances`, `serve_registry` (six downstream copies; bodies differ in their error arm — the widened W0-G3 census says which are exact; the rest unify behind one `on_error=` parameter in a CHANGE) | R1 |
| `agent_runtime/store_events.py::emit_store_event` | `_emit` in `board_store`, `dispatch_store`, `office_store` | R1 |
| `agent_runtime/store_conflicts.py` | `_guard_no_conflict` (board/office, 3 lines each — under the gate's floor, caught by name), and the `adopt_remote_*` / `resolve_conflict` shape shared by `BoardStore` and `OfficeStore` (50–136 lines each; a near-duplicate the alpha-renamed census will size) | R1 |
| `agent_runtime/serde.py::safe_text` | `_safe_text` in nine downstream `agent_runtime` files (`board_store`, `child_events`, `events`, `parity`, `persona_chat_continuity`, `persona_profile_binding`, `running_work`, `snapshot`, `tool_turn_history`) — the 2026-08-19 fold took `_text`/`_optional_text`/`_norm`; `_safe_text` is the same function one more name over | R1/R2 (whichever lands first creates the authority) |
| `agent_runtime/refusals.py::refusal` | `_refusal` in `flow_graph_sync`, `level_sync`, `mission_chat_workdir`, `persona_config_sync`, `harness_parts/gateway_commands`, `tools/agent_chat_tool` | R4 creates, T1/H folds |
| `agent_runtime/running_work/collect.py::row` | `_row` in `gateway_peers`, `realm_sync`, `running_work`, `discussions/attempt_store`, `discussions/native` | R2/R4 |

Not folded, named so nobody re-finds them: the 60-file `__getattr__` group and the `hermes_cli/{pty_bridge,win_pty_bridge,config,install_method,auth_codex,nous_billing,tools_config,web_routers/*}` pairs are upstream files — out of scope by rule 1.9. `agent_runtime/chat_turn.py` and `errors.py`'s twin `__init__`s are 4-line dataclass constructors, not helpers.

W0-G3's widened census (alpha-renamed, methods included) will find more than this table; the builder pastes its count into the W0 commit and the lanes fold what falls in their files. A fold is a CHANGE commit with the positive control of rule 1.3.

---

## 6. Method and landing protocol — the launcher playbook, applied

The launcher's program wrote down what its method cost and what it bought (`EterniaLauncher/docs/tooling/SUBAGENT_DEPLOYMENT_PLAYBOOK_2026-09-21.md`: 2 units retired per day under per-file design notes and hash-proved moves, 17 per day under cluster sheets and bulk mode; SHA span receipts caught 0 defects across the program, applied positive controls caught all of them). This plan starts where that playbook ended. The twelve rules below are its rules of record, restated once as facts.

### 6.1 Three kinds of lane, and who runs them

| lane | model | what it reads | what it produces | cap |
|---|---|---|---|---|
| **Design sitting** | strongest model, **ONE at a time** (two together exhausted a session limit) | this plan's lane row, the tree, the reuse inventory (§5), the prior sheets | ONE layout sheet per lane (a cluster of 2–10 files), ≤ 150 lines per file, **committed and pushed per file as it finishes** so review starts on the first while the last is being written. The reuse census (what duplicates an existing authority, what two files both mint) is in the sheet HEADER — a sheet cannot re-mint | — |
| **Review-and-fix** | Opus, one lane per sheet | the sheet, the tree | verifies arithmetic, import cycles, promotions, the size triple, the census against §5; APPLIES its own blocking fixes; **RUNS the sheet's named killing mutations once and records each red** (a mutation that has not been run is a belief — the office-host sheet named five and all five survived on the tree until the exec lane planted them); marks the sheet APPROVED. A second pass only if the first says the design is wrong. Recommendations inside a sheet are the defaults of record; the lane never stops to ask | one pass |
| **Bulk exec** | Opus, **uncapped in parallel** (they only run touched tests) | `EXEC_CARD` (§6.3) + the sheet | ONE MOVE commit, ONE CHANGE commit, ≤ 1 `style:`; tree wins over sheet and the message says so; G1 row deleted in the commit that crosses 800; push per commit; **reports its tool-call count** (the per-unit efficiency number: 210 calls for 3 units became 38–61 under this method) | ≤ 30-line report, ≤ 3 rows, defects in code or design only |
| **Batched landing** | Opus, **ONE at a time**, lands EVERY branch finished when it starts | the card's Landing section + the orchestrator's holding file (per branch: tip, MOVE/CHANGE SHAs, rows verbatim, what to scope-review) | rebase in a landing worktree; scoped review of CHANGE commits only (a proved MOVE-only branch skips review); the four gates **concurrently**; one `[ds-size]` ledger row at the count the gate prints; push `HEAD:main`; fast-forward the primary; remove worktrees and branches | — |

A branch that finishes after a landing has started waits for the next landing, unless the landing has only just started, in which case a message adds it to the batch.

### 6.2 What a lane runs — and what it never runs

- **Exec lanes while working:** `python -m pyflakes`/`ruff` on the touched modules (foreground, explicit timeout). Nothing heavier.
- **Exec lanes at the end:** ONLY the test files that import a touched module (`grep -l` the module paths under `tests/`), as one `pytest -q -p no:cacheprovider <files>` **run directly**, in the background with a log and the exit code captured unpiped (`; rc=$?; exit $rc`). Never the full suite, never the tooling gates, never `| tail`.
- **The landing, once, concurrently:** (a) the full `pytest` (the one heavy slot), (b) W0-G1..G4 + `test_duplicate_helper_bodies` + `test_cli_contract_dump`, (c) `scripts/changed_line_mutation_check.py` for any new gate, (d) the docs gates (`tests/test_docket_stage_claims.py` — note its `test_every_stage_that_says_it_shipped_names_a_commit_that_landed_here` is RED on today's `main` for `duplicate-implementation-retirement.md`, a pre-existing failure this program does not own; the lander names it as tolerated, not baselined). (b)–(d) need no slot and do not wait on (a).
- **After a forced re-rebase:** re-run only the tooling gates (b). The full suite runs again only if an incoming commit touches a file the batch touches.
- A serial gate chain under exec-lane load cost the launcher's first landing 40 minutes; this is why (a)–(d) launch together.

### 6.3 `EXEC_CARD` — the one page an exec lane reads (lands in Wave 0 as `docs/agent-runtime-harness/planned/downstream-god-file-refactor-EXEC_CARD.md`)

Setup: `git fetch` from a neutral cwd; `git worktree add <root>/<lane> origin/main -b refactor/<lane>`; never `checkout`/`switch` in the primary; never amend; never force-push; never push to `main`. Discipline: rules 1.1–1.9 stated as facts; MOVE then CHANGE; import sets from the moved span's free identifiers, never by subtraction; positive control tried on a throwaway copy, red pasted, reverted; promotion only with a production caller outside the module; G1 row deleted in the crossing commit; format AFTER the row is gone (a formatter grows a grandfathered file and the GREW arm has no legal repair — measured on the launcher at 835 → 847); a sheet step that ADDS code and moves none is grouped with a shedding step, never its own commit on a grandfathered file; re-anchor doc cites by symbol; source-pin census before every move (rule 1.6); push after every commit; leave the worktree in place (never remove one a lane could resume in; never dispatch a follow-up into another lane's worktree — message the lane).

### 6.4 The brief (owner ruling, in the launcher's CLAUDE.md; adopted into this repo's fork-owned [`CLAUDE.md`](../../../CLAUDE.md) "Briefing a subagent" so every hermes session sees it, not only this plan)

A brief is a work order: setup commands, the one page to read plus the sheet section, the steps, the report fields with a cap. No history, no rationale, no restated rules; a judgment call gets a one-line decision rule ("if the tree differs from the sheet, follow the tree and say so in the commit"). **≤ 40 lines, 25 for a mechanical lane.** Reports ≤ 30 lines.

### 6.5 What the orchestrator keeps

A holding file per landing outside the repo (branch tips, commits to review, rows verbatim, expected `[ds-size]` count) and a RESUME line in session memory after every lane report: `main` tip, count, every live worktree and what to do when it reports. A lane's report lives only in its notification — it is copied into the holding file the moment it arrives.

### 6.6 Repo facts that shape the landing

- **Shared index** (`feedback_shared_git_index`): concurrent sessions share ONE index; stage and commit in one breath.
- **No pre-push hooks** by ruling (2026-09-03); gates are tests and the lander runs them; CI (`tests-os.yml`) runs the full suite per OS on the push and is watched, not waited for.
- **Findings go to the queue by surface**; a report is evidence, never a backlog; a deletion discharges its row in the same commit.

---

## 7. What the operator owes (the only two things that wait)

1. **One boot on the H4 build** — the RL-20/RB-9 restart fence lives in the code H4 turns into a class; RB-7/RO-9 are the gates, but the "runtime survived two restarts" proof the boot-sweep plan established is a field proof. Read the receipts; if the drain or the socket lock behaves differently, H4's CHANGE commit is reverted (its MOVE stands).
2. **The §4.2 rulings** where the launcher still lowers a verb to argv: those rows wait for the launcher's method-lane row to land first; the operator says which order.

Everything else — layouts, folds, the §4.1 recommendations, the §4.3 rulings — is decided by the lane and its sheet review (rule 1.10).

---

## 8. Ledger

| lane | status | MOVE | CHANGE | `[ds-size]` after | notes |
|---|---|---|---|---|---|
| W0 | planned | — | 1 commit | 41 | gates + reach census |
| H1 | planned | — | 2 | 41 | parts → modules; §4.2 deletions |
| S1 | planned | 1 | — | 40 | first Wave 2 landing |
| H2 | planned | 1 | 1 | 39 | parser table; trampolines gone |
| H3 | planned | 1 | 1 | 38 | `TurnCommit` |
| R1 | planned | 1 | 1 | 32 | 6 files |
| R2 | planned | 1 | 1 | 23 | 9 files |
| R3 | planned | 1 | 1 | 13 | 10 files |
| R4 | planned | 1 | 1 | 7 | 6 files |
| C1 | planned | 1 | 1 | 5 | 2 files |
| T1 | planned | 1 | 1 | 3 | 2 files |
| D1 | planned | 1 | — | 1 | 2 files |
| H4 | planned | 1 | 1 | 0 | `ServeSession`; §7 boot |

Thirteen lanes, **≤ 27 commits** for 41 files (plus at most one `style:` per lane). That is the "big moves, few commits" shape: a lane is one worktree, one builder, one MOVE and one CHANGE, and a regression bisects to one of two commits per lane.
