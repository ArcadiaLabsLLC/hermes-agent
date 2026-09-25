# Planned — the god-file program (2026-09-24 refresh): 62 fork files, the enterprise bar, and the gates that hold it

**Status:** DESIGN 2026-09-24 (Fable, lane GOD-D, read-only against `main` @ `78501db796`); **Wave 0 + Wave 1 LANDED the same day** (§3.1a — four hashes, `[ds-size]` 40/73,870 → 37/58,300); **Wave 2 first batch SHEETED** (§3.1b, lane GOD-S2 against `bf4377f226`), not dispatched. This note is the **refresh of [`downstream-god-file-refactor.md`](downstream-god-file-refactor.md) (2026-09-21)** — that plan stays the program's spine (its §0.1 counter, §0.2 fence, §0.4 exec trap, §0.5 gates, §1 rules 1–11, §2 lane layouts, §3 order, §5 duplicate list, §6 method, §7 owed, §8 ledger). This note re-takes its numbers (41 → 62 files), adds the owner's 2026-09-24 bar as rules with gates, moves the dead-code list into a launcher-format queue, and names which §§ of the 09-21 plan it supersedes (§1 below). Where the two disagree, THIS note wins, and the 09-21 plan is amended at Wave 0 to point here. Layout sheets for wave 1: [`god-file-layout-sheets/`](god-file-layout-sheets/). Dead code: `Harness_Brain/20 — Active Initiatives/dead-code-burn-down-queue.md`. Weakness escalation per domain: fork `CLAUDE.md` § "Weakness escalation".

**The owner's brief (2026-09-24, verbatim intent).** *God file breakups … broken down but also refactored to be enterprise grade, no if if if else routing, code legibility dramatically up, how the codebase connects legibility and structure up, unification of helpers and code blocks reusable; as you go a dead code deletion list like we did in the launcher; add weakness escalation per domain to the todo / agents.md like in launcher.* And: every fork `.py` over 800 lines — 62 files, 120,253 lines (`X:/wt/_holds/god-files-over-800-2026-09-24.txt`, re-taken in §0).

## SCOPE RULE (owner, 2026-09-24, binding on every deliverable)

The program is for **FORK code only**: `agent_runtime/`, `plugins/eternia-harness/`, `hermes_cli/harness.py`, `hermes_cli/harness_parts/`, and fork-only files (`scripts/`, `tests/_downstream/`, and the fork-only files under `agent/charsheet/` and `tools/` — §0.3 note). Nothing in the program, the sheets, the dead-code queue or the gates may touch an upstream file, and **no target module may be placed inside an upstream package's file**. A new module goes under `agent_runtime/`, `hermes_cli/harness_parts/`, `plugins/eternia-harness/`, `scripts/<pkg>/` or `tests/_downstream/` — never at the top level of `hermes_cli/`, `tools/`, `agent/`, `gateway/`. If a god file's breakup needs a seam in upstream, that is a **held widening-PR row** in [`upstream-footprint-ledger.md`](upstream-footprint-ledger.md), not a move. Where a fork god file reaches into upstream internals today, its sheet names the **upstream door** it should use instead (plugin hook, config key, call parameter) per the second-door rule ([`second-doors-2026-09-24.md`](second-doors-2026-09-24.md); ADR `Harness_Brain/30 — Decisions/0013`'s 2026-09-23 amendment and seam rules 9–10). W0-G2 (the upstream fence) is the mechanism; this paragraph is the rule it enforces.

---

## 0. Ground truth (2026-09-24, `main` @ `78501db796`)

### 0.1 The instruments (every number below was taken by them; re-take, never copy)

- **Lines:** `wc -l` (the owner's list) AND the 09-21 plan's code-line counter (non-blank, not `#`-led; docstrings count). Both are printed; §9 Q1 asks which one the gate binds.
- **The probe** (Appendix A; Wave 0 lands it as `scripts/god_file_probe.py`): per file, top-level defs, longest function (`end_lineno − lineno + 1`), **if-chains ≥ 3 arms** (an `If` that is not itself an `orelse` arm, counting its `elif`/`else` arms), of which **routed** = any arm tests `== "str"` / `in ("a","b")` / `isinstance(...)`; plus two density counts that catch what an `elif` count cannot — `str==` (every `Compare` against a string constant) and `isinstance` calls. The 09-21 census counted none of these; they are the owner's "if if if else" measured.
- **Dead-code census:** per top-level def in the 62, files referencing the name (token match) across production `.py` excluding its own file, own-file references beyond the `def`, test files referencing it. Decorator-registered defs are printed and struck by hand (the `@method(...)` registry), exactly as the 09-21 field notes did.
- **Not run:** no coverage pass (W0-D still owed), no suite, no serve; nothing written outside `docs/`, `Harness_Brain/`, `CLAUDE.md`.

### 0.2 The 62, measured (raw · code · top-level defs · longest function · if-chains ≥ 3 arms / routed · `str==` · `isinstance`)

Order = the owner's list (raw lines). `T` = the lane in §3 that owns the file.

| # | file | raw | code | defs | longest fn | chains/routed | str== | isinst | T |
|--:|---|--:|--:|--:|---|---|--:|--:|---|
| 1 | `hermes_cli/harness_parts/persona_commands.py` | 8191 | 6269 | 119 | `_mission_chat_commit_turn` 1590 | 2/1 | 31 | 30 | H3 |
| 2 | `hermes_cli/harness.py` | 6737 | 5240 | 164 | `populate_parser` 1768 | 6/2 | 28 | 11 | H2 |
| 3 | `hermes_cli/harness_parts/serve.py` | 6646 | 4041 | 46 | `serve_loop` 3760 | 2/1 | 27 | 30 | H4 |
| 4 | `agent_runtime/serve_rpc.py` | 4703 | 3518 | 62 | `_runtime_office_upsert` 333 | 1/0 | 1 | 44 | R3 |
| 5 | `agent_runtime/realm_sync.py` | 4464 | 3244 | 118 | `publish_realm_sync` 242 | 6/1 | 40 | 13 | R4 |
| 6 | `agent_runtime/core_cache.py` | 4073 | 2502 | 85 | `build_input_fingerprint` 236 | 1/0 | 2 | 20 | R3 |
| 7 | `agent_runtime/persona_assignments.py` | 4053 | 3172 | 56 | `open_chat` 203 | 0/0 | 6 | 2 | R1 |
| 8 | `agent_runtime/prompt_observability.py` | 3749 | 2933 | 98 | `mission_chat_prompt_observability` 501 | 5/5 | 29 | 118 | R2 |
| 9 | `agent_runtime/profile_runner.py` | 3596 | 2743 | 95 | `_execute_agent_run` 424 | 4/4 | 26 | 71 | R3 |
| 10 | `agent_runtime/serve_socket.py` | 2967 | 2194 | 33 | `_handshake` 127 | 0/0 | 6 | 17 | R3 |
| 11 | `agent_runtime/snapshot.py` | 2814 | 1775 | 53 | `_parity_envelope` 338 | 1/1 | 3 | 30 | R3 |
| 12 | `scripts/release.py` | 2704 | 2487 | 17 | `main` 158 | 1/1 | 4 | 0 | S2 |
| 13 | `agent_runtime/office_store.py` | 2493 | 1874 | 23 | `upsert_actor` 249 | 0/0 | 1 | 6 | R1 |
| 14 | `agent_runtime/persona_chat_history.py` | 2325 | 1753 | 60 | `persona_chat_history_summary` 270 | 0/0 | 24 | 26 | R2 |
| 15 | `hermes_cli/harness_parts/gateway_commands.py` | 2323 | 1645 | 35 | `cmd_gateway_peers_join` 443 | 0/0 | 20 | 19 | R4 |
| 16 | `agent_runtime/persona_chat_continuity.py` | 2240 | 1646 | 36 | `mint` 232 | 0/0 | 10 | 25 | R1 |
| 17 | `agent_runtime/gateway_peers.py` | 2185 | 1621 | 43 | `dial_peer` 172 | 0/0 | 2 | 20 | R4 |
| 18 | `agent_runtime/agent_create.py` | 2126 | 1439 | 33 | `perform_agent_create` 691 | 0/0 | 2 | 11 | R4 |
| 19 | `agent_runtime/mcp_admission.py` | 2073 | 1452 | 37 | `admit_mcp_servers` 198 | 0/0 | 0 | 5 | R3 |
| 20 | `agent_runtime/running_work.py` | 1964 | 1517 | 31 | `_collect_delegations` 233 | 0/0 | 4 | 21 | R2 |
| 21 | `agent_runtime/stream.py` | 1898 | 1385 | 30 | `stream_frames` 425 | 0/0 | 7 | 15 | R3 |
| 22 | `agent_runtime/dispatch_delivery.py` | 1712 | 1237 | 31 | `drain_background_completions` 240 | 3/0 | 3 | 3 | R2 |
| 23 | `agent_runtime/operator_channels.py` | 1670 | 1394 | 40 | `build` 203 | 2/0 | 27 | 26 | R2 |
| 24 | `scripts/run_tests_parallel.py` | 1657 | 1250 | 31 | `main` 626 | 1/0 | 11 | 0 | S2 |
| 25 | `agent_runtime/mission_chat_turns.py` | 1633 | 1156 | 48 | `_safe_elements` 84 | 1/0 | 4 | 32 | R2 |
| 26 | `agent_runtime/state_patches.py` | 1439 | 1023 | 27 | `build_state_patch` 82 | 0/0 | 0 | 5 | R3 |
| 27 | `agent_runtime/runtime_hud.py` | 1437 | 1103 | 37 | `render_situational_hud_block` 146 | 3/0 | 6 | 34 | R2 |
| 28 | `tests/_downstream/hermes_cli_conftest.py` | 1390 | 938 | 29 | `_sys_modules_identity_is_restored` 78 | 0/0 | 5 | 4 | T2 |
| 29 | `agent_runtime/persona_instance_sync.py` | 1357 | 975 | 28 | `apply_persona_instance_pull` 273 | 0/0 | 3 | 16 | R4 |
| 30 | `agent_runtime/dispatch_store.py` | 1308 | 1019 | 30 | `record_completion` 155 | 1/0 | 0 | 9 | R1 |
| 31 | `agent_runtime/terminal_envelope.py` | 1262 | 963 | 27 | `envelope_decision` 141 | 0/0 | 0 | 3 | R2 |
| 32 | `agent_runtime/harness_doctor.py` | 1262 | 831 | 21 | `_placement_census_report` 255 | 2/0 | 5 | 8 | R3 |
| 33 | `agent_runtime/config.py` | 1212 | 902 | 43 | `describe_runtime_default_authority` 72 | 0/0 | 5 | 33 | R3 |
| 34 | `agent_runtime/mission_chat_turn_context.py` | 1160 | 744 | 29 | `build_mission_chat_turn_context` 142 | 0/0 | 0 | 5 | R2 |
| 35 | `tests/_downstream/id_markers.py` | 1150 | 1015 | 11 | `pytest_collection_modifyitems` 26 | 0/0 | 1 | 0 | T2 |
| 36 | `scripts/changed_line_mutation_check.py` | 1150 | 831 | 31 | `run` 173 | 2/1 | 4 | 18 | S1 |
| 37 | `agent_runtime/serve_office_subscriptions.py` | 1115 | 642 | 8 | `subscribe` 261 | 0/0 | 1 | 12 | R3 |
| 38 | `agent_runtime/store.py` | 1114 | 911 | 28 | `delete` 124 | 0/0 | 4 | 4 | R1 |
| 39 | `scripts/generate_agent_runtime_stream_fixtures.py` | 1107 | 740 | 9 | `_build_agent_create_frames` 228 | 1/1 | 10 | 11 | S2 |
| 40 | `agent_runtime/serve_registry.py` | 1099 | 795 | 32 | `register_serve_instance` 92 | 2/0 | 2 | 7 | R3 |
| 41 | `scripts/ci/timings_report.py` | 1085 | 860 | 25 | `_gantt_bars` 114 | 3/1 | 3 | 1 | S2 |
| 42 | `agent_runtime/board_store.py` | 1085 | 925 | 16 | `_idempotent_replay` 88 | 0/0 | 1 | 4 | R1 |
| 43 | `agent_runtime/chat_live_log.py` | 1066 | 849 | 38 | `_backfill_rows` 82 | 1/1 | 8 | 6 | R2 |
| 44 | `agent_runtime/serve_gateway_auth.py` | 1058 | 746 | 25 | `redeem_pairing_code` 122 | 0/0 | 0 | 10 | R3 |
| 45 | `agent_runtime/persona_runtime.py` | 1048 | 761 | 18 | `mission_chat_reply` 264 | 0/0 | 2 | 3 | R2 |
| 46 | `agent_runtime/persona_profile_binding.py` | 1047 | 847 | 23 | `rebind_persona_profile` 215 | 0/0 | 1 | 0 | R4 |
| 47 | `agent_runtime/realm_revert.py` | 1031 | 768 | 16 | `revert_realm_sync` 159 | 4/0 | 3 | 1 | R4 |
| 48 | `scripts/doc_cite_adjacency.py` | 1003 | 759 | 26 | `run` 133 | 0/0 | 1 | 2 | S2 |
| 49 | `agent_runtime/media_handles.py` | 990 | 746 | 24 | `build_media_scope` 77 | 0/0 | 0 | 13 | R2 |
| 50 | `agent_runtime/persona_instance_identity.py` | 971 | 782 | 22 | `reconcile_persona_instances` 265 | 0/0 | 4 | 7 | R1 |
| 51 | `agent_runtime/machine_roots.py` | 961 | 736 | 35 | `resolve_mcp_servers` 52 | 3/2 | 2 | 25 | R3 |
| 52 | `hermes_cli/harness_parts/runtime_commands.py` | 945 | 681 | 22 | `_cmd_work_cancel` 123 | 2/0 | 7 | 4 | H2 |
| 53 | `agent_runtime/repo_context.py` | 939 | 762 | 44 | `_materialize_worktree_local_support` 73 | 0/0 | 6 | 0 | R4 |
| 54 | `scripts/run_tests_bundled.py` | 871 | 730 | 26 | `run` 152 | 2/1 | 11 | 2 | S2 |
| 55 | `agent_runtime/mission_chat_outcome.py` | 839 | 553 | 15 | `_guard_turn_outcome_vocabulary` 74 | 0/0 | 0 | 7 | R2 |
| 56 | `scripts/check-windows-footguns.py` | 835 | 646 | 14 | `scan_file` 75 | 2/1 | 10 | 0 | S2 |
| 57 | `agent_runtime/serve_stream_hub.py` | 825 | 632 | 6 | `subscribe` 95 | 0/0 | 0 | 1 | R3 |
| 58 | `agent_runtime/persona_chat_actor_prewarm.py` | 825 | 575 | 14 | `_prepare` 161 | 0/0 | 2 | 0 | R2 |
| 59 | `agent_runtime/patch_coverage.py` | 824 | 385 | 13 | `event_is_patch_coverable` 61 | 0/0 | 0 | 9 | R3 |
| 60 | `agent_runtime/chat_session_scope.py` | 824 | 615 | 22 | `_resolve_chat_scope` 100 | 1/0 | 2 | 4 | R2 |
| 61 | `agent_runtime/skill_promotion.py` | 813 | 613 | 22 | `execute_promotion` 173 | 0/0 | 5 | 0 | R4 |
| 62 | `agent_runtime/persona_config_sync.py` | 810 | 606 | 21 | `apply_persona_config_pull` 91 | 0/0 | 1 | 16 | R4 |
| | **TOTAL 62** | **120,253** | **88,496** | **2,301** | | **65 / 24** | **433** | **879** | |

**What the numbers say, before the tables are read as a to-do list.** (a) By the 09-21 code-line counter **34** of the 62 are over 800; the other 28 are over by raw lines only (comments and blank lines) — `patch_coverage.py` is 824 raw / 385 code. Q1 in §9. (b) The `elif`-chain count is LOW (65 in 120 k lines) because the fork's routing is written as **guard ladders** — `if op == "ping": …; return` × 11 in `serve.py::_handle_message` (serve.py:5191–5733), `if kind == "pairing_code"` × 3 in `_gateway_authenticator` (serve.py:839–895), `if op == "detach" / elif "add_parent" / …` in `_cmd_persona_instance_steer` (persona_commands.py:5769) — which the `elif` metric cannot see and the `str==` column can: **433 string comparisons, 879 `isinstance` calls**. The routing gate (W0-G5) is therefore specified on LADDERS and on `str==`-against-a-vocabulary, not on `elif` (§2.4). (c) The three biggest units are unchanged since 09-21 (`_mission_chat_commit_turn` 1,590 · `populate_parser` 1,768 · `serve_loop` 3,760) — the seam program moved the harness's REGISTRATION into `plugins/eternia-harness/__init__.py` (`build_cli_parser` → `populate_parser`, `_harness_entry`, `_install_harness_entries`) and left the tree itself where it was, so H1/H2's premise holds and H2 now splits the plugin-shaped parser, as ADR 0013 intended. (d) `_load_command_parts` and its `exec(compile(...), globals())` are still at harness.py:6730–6737 — the W0-G4 / H1 trap is live.

### 0.3 The fence, and four files the 62 list does not name

`git ls-tree upstream/main` ∖ `HEAD` still holds every file in the table; W0-G2 stays as the 09-21 plan wrote it. **Four fork-only `.py` files over 800 are absent from the owner's list**: `agent/charsheet/pipeline.py` (1,898 code), `agent/charsheet/draft.py` (1,599), `tools/agent_chat_tool.py` (1,430), `tools/agent_chat_dispatch.py` (842) — the 09-21 lanes C1 and T1. They are fork-only (not in `upstream/main`) but live in upstream DIRECTORIES, which is the only reason a `agent_runtime`/`harness`/`scripts`/`tests` sweep misses them. They stay in the program as C1/T1 (§3), under the scope rule's "new modules go under `agent/charsheet/`'s own package and a new `tools/agent_chat/` package", unless Q2 in §9 says otherwise. `apps/desktop/src/app/skills/mcp-tab.tsx` (09-21 lane D1) no longer exists — D1 is CLOSED.

### 0.4 The exec trap, the plugin door, and what the tests hold (re-verified)

Unchanged from the 09-21 plan §0.4 except for the entry: `plugins/eternia-harness/__init__.py::_setup_harness_parser` → `hermes_cli.harness.build_cli_parser(parser)` → `populate_parser`. `build_parser(parent_subparsers)` (harness.py:282) survives only for `scripts/dump_cli_contract.py` (`build_harness_parser` alias) and `serve.py::_build_harness_parser`; both are retargeted to `populate_parser` in H2 and `build_parser` is deleted (dead-code queue row). `hermes_cli/harness.py` still imports 14 `agent.charsheet`, 10 `agent.pet`, 6 `hermes_cli.auth`, 5 `agent.account_usage`, 4 `agent.credential_pool` names — every one an upstream door the sheet names (`god-file-layout-sheets/harness.md` § Doors); `serve.py` reaches `tools.process_registry`, `model_tools`, `hermes_cli.config`, `agent.ssl_guard`, `agent.process_bootstrap`; `persona_commands.py` reaches `tools.registry`, `tools.terminal_tool_lifecycle`, `gateway.session_context`, `agent.title_generator`, `hermes_cli.flag_binding`. None of these is edited; a lane that needs one widened files a ledger row.

### 0.5 Existing gates (unchanged list; one addition)

The 09-21 plan §0.5 list stands: `test_duplicate_helper_bodies.py` (`_GRANDFATHERED` at line 81, module-level functions in `agent_runtime/` only), the CLI contract fixture, the tombstone registry, `scripts/changed_line_mutation_check.py`, the CI runner. **Addition since 09-21:** `tests/tooling/test_plugin_imports_public_surface.py` (the seam program's gate that the plugin imports only public names) — the model for W0-G6's import-graph gate, and the reason W0-G6 lands beside it rather than as a new directory.

---

## 1. What this refresh keeps, and what it supersedes (each with its reason)

| 09-21 § | verdict | why |
|---|---|---|
| §0.1 counter | KEPT, plus raw lines | the owner's list is raw; Q1 decides which one the gate binds |
| §0.2 fence, §0.4 exec trap, §0.5 gates | KEPT | re-verified today (§0.4); nothing moved |
| §0.3 the 41 | **SUPERSEDED by §0.2 above (62 + C1/T1's four)** | 21 files over by raw lines and nine `scripts/` + two `tests/_downstream/` files were out of the 09-21 sweep; D1 closed (file gone) |
| §1 rules 1–11 | KEPT verbatim | the bar below ADDS rules 12–17; none of 1–11 is loosened |
| §2 Wave 0 (G1–G4, W0-D) | KEPT, **extended** with W0-G5/G6/G7 (§2.4) and the probe | the owner's bar has no gate in the 09-21 plan |
| §2 H1 | KEPT unchanged | "the one lane every harness lane waits on" — the 263-patch trap is still on the tree |
| §2 H2/H3/H4 layouts | KEPT as the target module lists; **the sheets in `god-file-layout-sheets/` carry line ranges, routing sites, helpers and dead code** and supersede the 09-21 tables where they differ (each sheet says where) | the 09-21 tables were symbol-only by rule; the owner asked for sheets with hashes/line ranges |
| §2 R1–R4 | KEPT, **widened** with the 18 agent_runtime files new to scope (§3.2) | same responsibility grain, more rows |
| §2 C1, T1 | KEPT (pending Q2) | fork-only files in upstream directories |
| §2 D1 | **CLOSED** | `mcp-tab.tsx` no longer exists on `main` |
| §2 S1 | KEPT, joined by **S2** (the other eight `scripts/`) and **T2** (`tests/_downstream/`) | owner scope: scripts and `tests/_downstream` are fork code, ordered after the runtime files |
| §3 order | KEPT (W0 → H1 → {H2,H3} → H4; S1 → parallel), S2/T2 appended LAST | owner: "order them after the runtime files" |
| §4 dead-code list | **SUPERSEDED as a LOCATION**: the rows now live in `Harness_Brain/20 — Active Initiatives/dead-code-burn-down-queue.md`; §4 stays as evidence | launcher rule: a report is evidence, never a backlog |
| §5 duplicate list | KEPT, re-verified by name today (§4 below), two rows added | `_now_iso` × 4, `_try_lock` in `serve_socket` too |
| §6 method, §7 owed, §8 ledger | KEPT; ledger re-cut in §8 | — |
| ADR 0013 order (seams → refactor) | KEPT: seam Stage 1 has landed; "the refactor's start is decided after the ratchet is re-measured" is the remaining owner act | `fork-hygiene-queue.md` ORDER 2 row's 2026-09-24 verdict |

---

## 2. The bar, as testable rules (rules 12–17; 1–11 are the 09-21 plan's)

Each rule states the guarantee, the gate that holds it, and how the gate is mechanised. A gate proves a POSITIVE guarantee at runtime or through the AST/import graph; a source walk only proves a NEGATIVE ("this is never written") — the launcher's rule, adopted.

12. **Routing is data, never a ladder on a string or a kind.** Any place that maps a *vocabulary* (an `op`, a `kind`, a `mode`, a frame `event`, a step name, an RPC method, a parser family) to a *behaviour* is a **dispatch table** (`Mapping[str, Callable]`, frozen at module scope), a **registry** (the `serve_rpc._METHODS` + `@method` pattern, which is already correct and is the reference implementation), or a **strategy object** (one class per kind behind a `Protocol`). The remaining `if` is a GUARD (a precondition that refuses) or a BOUNDARY (validate-then-dispatch); never a third arm. Vocabulary membership lives in ONE `Final` tuple/`Enum` beside the table, so an unknown key is a typed refusal, not a fall-through. — **Gate W0-G5** (§2.4).
13. **One write path per state.** Every persisted or shared-mutable state (a store file, a registry row, an inflight table, a subscription set) has exactly one function or method that writes it, named `_write_*`/`_commit_*`/`record_*`, and every other site calls it. — **Gate:** the widened duplicate gate (W0-G3) catches copied write bodies; the sheet's "write sites" table is the positive control the review lane runs (grep the store's file/attribute name for `open(... "w")`, `.write_text(`, `json.dump(`, `[...] =` outside the owner).
14. **Typed reasons.** A refusal, a drop, a fallback or a skip carries a reason from a closed vocabulary (`Enum` or `Literal`) and is emitted through one helper (`refusals.refusal(kind, detail)` — the 09-21 §5 `_refusal` fold becomes the authority), never a free string in a dict. — **Gate:** W0-G5's `str==` arm applied to `reason`/`refusal` keys; the `mission_chat_outcome._guard_turn_outcome_vocabulary` pattern is the model (a vocabulary guard that fails at import).
15. **Helpers are unified into named modules with one owner each.** `serde.py` (parsing/coercion: `positive_int`, `safe_int`, `safe_text`, `read_json`, `write_json_atomic`), `file_locks.py`, `store_events.py`, `store_conflicts.py`, `refusals.py`, `paths.py`, `clock.py` (`now_iso` — new, four copies today). A helper with the same name in two modules is a red (W0-G3 widened to NAME collisions among private helpers ≥ 4 lines, not only bodies). — **Gate W0-G3** as the 09-21 plan widened it, plus the name arm.
16. **A module map a reader can follow from entry point to store.** Every package created by the program has an `__init__.py` docstring that is a MAP: entry points (what calls in), the lanes (one verb family per module), the stores it writes, and what it must never import (the layer below it may not import the layer above). Layers, in order: *models/value types* → *pure policy/resolvers* → *stores and I/O* → *lanes and handlers* → *wiring/registration/probes* (09-21 rule 2's grain, now ORDERED). — **Gate W0-G6** (import-graph): each module declares its layer in a `__layer__ = "policy"` module constant (or the map's table), and the gate walks `ast` imports and reds an import from a lower layer to a higher one, and any import of `hermes_cli.harness` from a part.
17. **The legibility floor per function.** No function over **150 lines** and no nesting deeper than **4** in a file the program has opened (the launcher's 30 % target is retired; these two are per-unit, measurable, and what "legibility dramatically up" means when a reader opens the file). Closures that read more than three enclosing locals become methods on an object whose fields are those locals (`serve_loop` → `ServeSession`, `_mission_chat_commit_turn` → `TurnCommit`). — **Gate W0-G7** (the probe run as a test, grandfathered like G1, shrink-only).

### 2.4 The Wave 0 gates, extended (G1–G4 and W0-D unchanged from 09-21 §2)

| id | gate | asserts | mechanism | baseline | killing mutation |
|---|---|---|---|---|---|
| **W0-G5** | `tests/tooling/test_no_ladder_routing.py` | in every fork production `.py`: (a) no **ladder** — ≥ 3 sibling `If` statements in one body whose tests compare the SAME name (`op`, `kind`, …) against string constants, whether `elif`-chained or `return`-terminated guards; (b) no `isinstance` chain ≥ 3 arms on one name; (c) no `Compare` against a string that is a member of a vocabulary declared elsewhere as a `Final` tuple/`Enum` (the table is the only reader of its own vocabulary) | AST walk (a NEGATIVE guarantee — a source walk is the right instrument); the vocabulary set for (c) is enumerated FROM the `Final`/`Enum` declarations by the same walk, never typed into the test | a fixture `tests/fixtures/ladder_routing_grandfathered.json` with today's sites, one row per `(file, function, name, arms)`, shrink-only like G1; the probe prints the starting count (`str==` 433 is an upper bound; the ladder count is what the gate's own first run prints and the W0 builder pastes) | re-add `if op == "ping": …` `if op == "hello": …` `if op == "version": …` as siblings to any handler → red naming the function and the name |
| **W0-G6** | `tests/tooling/test_fork_import_layers.py` | every module under `agent_runtime/`, `hermes_cli/harness_parts/`, `plugins/eternia-harness/` declares `__layer__` (or is listed in its package map) and imports only same-or-lower layers; no part imports `hermes_cli.harness`; no fork module imports a `_private` name from an upstream module (the second-door rule made mechanical) | AST import walk + a runtime import of each package's `__init__` to read the map (POSITIVE: the map is bound, not spelled) | none — the layer constant is added in each lane's MOVE commit; files not yet opened are exempt by the grandfather list until their lane | give `store.py` `from .serve_rpc import method` → red (store → wiring is up) |
| **W0-G7** | `tests/tooling/test_function_legibility_floor.py` | no function > 150 lines, no nesting > 4, in any fork production `.py` | the probe's AST (runtime `ast`, not regex) | `tests/fixtures/legibility_grandfathered.json`, shrink-only; today: every "longest fn" cell in §0.2 over 150 (28 files) plus the nested-closure sites of §0.2(b) | add 1 line to a listed function → GREW red; a new 151-line function → red |
| **W0-P** | `scripts/god_file_probe.py` (Appendix A) | prints §0.2 for any file list | — | — | not a gate |

Landing: ONE Wave 0 commit as before (`test(tooling): W0 — …`), each gate with its killing mutation recorded through `scripts/changed_line_mutation_check.py`; the `[ds-size]` line now prints **two** counts (`raw=62 code=34`) until Q1 binds one. W0-G4 stays `xfail(strict=True)` until H1.

---

## 3. Lanes, order and the per-file target shape

### 3.1 Order (the 09-21 §3 diagram, with S2/T2 appended)

```
W0 ──► H1 ──► H2 ──┐
              H3 ──┼──► H4 (last of the harness lanes; §7 boot)
S1 ──► R1 · R2 · R3 · R4 · C1 · T1        (any order, any parallelism)
                    └──► S2 ──► T2        (LAST: scripts, then tests/_downstream — owner order)
```

Dependency-first, smallest blast radius first inside each wave: within R1–R4 a lane opens its files in ascending patch-site count (the 09-21 §0.3 column), so the file the most tests pin is moved with the most retargets already rehearsed.

### 3.1a Wave 1 — DONE 2026-09-24 (W0 + H1–H4; four landings on `main`)

| lane | landing on `main` | what landed |
|---|---|---|
| W0 | `7425b754a7` (tier commit) | `scripts/god_file_probe.py` + the five grandfather fixtures; gates G1–G7 live |
| H1 | `73201f631e` | the seven exec'd parts are modules; W0-G4 to the full form |
| H3 | `d0639591b0` | `persona_commands.py` → `harness_parts/persona/` (21 modules); `TurnCommit` phases |
| H4 | `d567f07f62` | `serve.py` → `harness_parts/serve/` (16 modules + `serve_gateway_credentials.py`); `ServeSession`, `OP_HANDLERS`, `CREDENTIAL_KINDS`, `EndReason` |
| H2 | `bf4377f226` | `harness.py` → 98 code lines; `parser/`, `usage/`, `characters/` + 12 modules; `_upstream_doors.py` ×2; `clock.py`; `serde` folds |

`[ds-size]` (code counter, ruling Q1): **W0 baseline `units=40 total=73870`** (`7425b754a7`) → after H1 `units=40 total=73803` → after H4 `units=39 total=69761` → after H3 `units=39 total=67503` (rebased onto H4) → **after H2 `units=37 total=58300`** (`scripts/god_file_probe.py --check` on `bf4377f226`, 2026-09-24: every arm `0 NEW, 0 GREW, 0 STALE`). Three files and 15,570 code lines left the ceiling population in one day. What the four lanes recorded as "where I followed the tree over the sheet" — import cycles inside a sheet's layout (H3), a module over 800 when two groups joined (H4's `session.py` at 1,016, H2's `runtime_commands`), a table's owner module crossing the ceiling (H4's credential table → a new module) — is folded into every Wave 2 sheet's §1 as drawn import edges with the layer derived from what each module actually imports, lazy imports included (the gate's `imports_of` walks every `Import` node).

### 3.1b Wave 2 — the first batch (ten `agent_runtime/` sheets, 2026-09-24, lane GOD-S2)

Sheets in [`god-file-layout-sheets/`](god-file-layout-sheets/): `serve_rpc.md`, `realm_sync.md`, `core_cache.md`, `persona_assignments.md`, `prompt_observability.md`, `profile_runner.md`, `serve_socket.md`, `snapshot.md`, `office_store.md`, `persona_chat_history.md`. Two rulings the sheets apply as facts: **every package is named after its file** (`agent_runtime/serve_rpc/`, `agent_runtime/persona_assignments/`, …), because 41–72 test files and up to 60 production importers spell each path and the H3/H4 precedent (package = old module name, `__init__` = the public names) kept all of them green through the MOVE — the 09-21 §2 names (`persona_instances/`, `office/`, `persona_chat/history/`) are retired; and **a class is moved whole for exactly one commit** (`PersonaInstanceStore`, `OfficeStore`, `_execute_agent_run`, `mission_chat_prompt_observability`) — the H4 `loop.py` precedent — then split by composition in the CHANGE.

**Order inside each lane and the parallel groups.** Four lanes run in parallel; inside a lane the files are sequential, ordered so that a file lands before the files that import it at module level, and the helper owners (`clock.now_iso`, `serde.read_json`/`positive_float`, `store_conflicts`, `store_events`, `file_locks`, `redaction`'s scrubbers, `git_cmd`) are created by the FIRST sheet that needs them and folded toward by every later one ("tree wins" when two lanes race to create the same owner — the second folds).

| group | lane | files, in order | why this order |
|---|---|---|---|
| G1 | R1 | `persona_assignments` → `office_store` | `office_store` lazily imports `identity` (R1's leaf); `store_conflicts`/`store_events` are created in the second |
| G2 | R2 | `prompt_observability` → `persona_chat_history` | disjoint importers; both fold `_safe_int` toward `serde` |
| G3 | R4 | `realm_sync` | alone in this batch; `git_cmd` created here |
| G4 | R3 | `serve_rpc` → `serve_socket` → `core_cache` → `profile_runner` → `snapshot` | `serve_rpc` creates `clock.now_iso`; `core_cache` imports two `serve_socket` constants at module level; `snapshot` imports six of the ten at module level and is **last of Wave 2** — its `__layer__` declarations land only after the three lazy reaches into it (`core_cache.contract_versions`, `prompt_observability.skills_catalog_by_hash`, `office_store`'s actor cap) are closed by their own sheets |

Parallelism is safe across groups because each package re-exports every name its importers take today; the only cross-group edits are the two coordinated one-liners the sheets name (`MAX_OFFICE_ACTORS_PROJECTED` → `office_models.py`, R1/R3; the `_default_session_db` wrapper, R1/R2), each with a "tree wins" rule. **Second batch** (not yet sheeted): the 18 remaining R1–R4 files of §3.2, in the same groups, after this batch lands.

**Two owner questions the sheets raise** (each with the default the lanes apply until answered): (Q6) three ladder/routing sites have **no test reaching them today** — `persona_assignments._persona_instance_is_active_lane`, `serve_socket._os_error_token`, `realm_sync.sync_artifacts_for_workspace_agent`'s caller — so their killing mutations are green by construction; the sheets land a positive control FIRST, in the MOVE (default: yes, a control before the table — the capture-is-a-vehicle rule). (Q7) `prompt_observability` and `profile_runner` reach three PRIVATE upstream names (`_compression_threshold_for_model`, `_find_all_skills`, `_sanitize_surrogates`); the sheets route each through `agent_runtime/_upstream_doors.py` and file a held widening row per name in `upstream-footprint-ledger.md` (default: door now, widening PR when the next upstream batch is cut).

### 3.2 Target shape per file — the module list, one line each, and the seam each exposes

The 09-21 §2 tables stand for the 41 they cover (H2, H3, H4, R1–R4, C1, T1, S1); the three wave-1 sheets carry line ranges. Below: the **21 files new to scope** plus the two whose 09-21 row this refresh changes. Format: `file → modules` · *seam* (what the outside calls).

**R1 (stores)** — adds `persona_instance_identity.py` (50) → `persona_instances/identity/{aliases,classify,reconcile,evidence}.py` · *seam:* `reconcile_persona_instances(store, …)` + typed `HeldReason` Enum replacing `_held_reason_for`'s string set.

**R2 (chat lane)** — adds `mission_chat_turn_context.py` (34) → `mission_chat_turn_context/{resolvers,context,signature,skill_preload}.py` · *seam:* `build_mission_chat_turn_context(request, resolvers)`; the twelve `_default_*` resolvers become one `MissionChatTurnResolvers.defaults()` classmethod (they are a strategy object already, spelled as twelve functions). `persona_runtime.py` (45) → `persona_runtime/{runtime,prompts,tool_scope,soul_overlay}.py` · *seam:* `GPTPersonaRuntime`. `media_handles.py` (49) → `media/{artifacts,scope,cache,declarations}.py` · *seam:* `build_media_scope`, `resolve_handle`. `mission_chat_outcome.py` (55) → `mission_chat_outcome/{vocabulary,refusals,plan,finalization}.py` · *seam:* the `TurnOutcome`/`ChatErrorKind` vocabulary — the model for rule 14. `persona_chat_actor_prewarm.py` (58) → `persona_chat/prewarm/{spans,worker,boot}.py` · *seam:* `request_chat_actor_prewarm`. `chat_session_scope.py` (60) → `chat_session_scope/{scope,head,home}.py` · *seam:* `resolve_chat_session_scope`; `_resolve_chat_scope` (100) → a `ChatScopeResolution` table keyed by `ChatHeadSource`.

**R3 (serve, runtime, cache)** — adds `serve_office_subscriptions.py` (37) → `serve_office/{subscriptions,fold,sink,keys}.py` · *seam:* `OfficeSubscriptions.subscribe` (261 → ≤ 150 by lifting `_delta_touches_workspace` and the fold negotiation into `fold.py`). `serve_registry.py` (40) → `serve_registry/{rows,classify,ended,stderr_logs,probe}.py` · *seam:* `register_serve_instance`/`classify_serve_instance`; the `_looks_like_serve` argv probe stays only as the foreign-row fallback (`fork-hygiene-queue` GREEN verdict). `serve_gateway_auth.py` (44) → `serve_gateway_auth/{devices,pairing,proofs,store}.py` · *seam:* `verify_device_proof`, `redeem_pairing_code`; the four-hello dispatch in `serve.py::_gateway_authenticator` becomes a `CREDENTIAL_KINDS: Mapping[str, Callable]` table HERE, with `_credential_kind` its only reader. `serve_stream_hub.py` (57) → `serve_stream_hub/{subscription,producer,hub}.py` · *seam:* `StreamHub`. `patch_coverage.py` (59) → stays ONE module (385 code lines) with its comment history relocated per rule 7 — a raw-line file, Q1. `machine_roots.py` (51) → `machine_roots/{registry,expand,mcp_templates,issues}.py` · *seam:* `load_machine_roots`, `resolve_mcp_servers`.

**R4 (sync, gateway, create)** — adds `realm_revert.py` (47) → `realm_sync/revert/{classify,actions,upstream,run}.py` · *seam:* `revert_realm_sync`; `_revert_one`'s four `chains≥3` become a `REVERT_ACTIONS: Mapping[RevertAction, Callable]` (the `RevertAction` Enum already exists — this is the cleanest rule-12 conversion in the tree and the exemplar sheet for R4). `repo_context.py` (53) → `repo_context/{execution,worktrees,reap,excerpts,labels}.py` · *seam:* `isolated_repo_context_for_run` (dead-code queue: test-only today). `skill_promotion.py` (61) → `skills/promotion/{plan,classify,execute,inbox}.py` · *seam:* `classify_promotion` → `execute_promotion`. `persona_config_sync.py` (62) → `persona_config_sync/{projection,baseline,pull}.py` · *seam:* `apply_persona_config_pull`.

**H2** — adds `hermes_cli/harness_parts/runtime_commands.py` (52) → `harness_parts/{runtime_commands,work_commands,verify_commands}.py` · *seam:* the parser `func=` targets; `_cmd_work_cancel` (123) → a `WorkCancelOutcome` object.

**S1** (unchanged) `scripts/changed_line_mutation_check.py` → `scripts/mutation_check/{claims,partition,run,report}.py` + ≤ 60-line entry. **S2** — `scripts/release.py` (12) → `scripts/release/{git,versions,changelog,authors,main}.py` · *seam:* `main()`; `scripts/run_tests_parallel.py` (24) → `scripts/test_runner/{discover,slices,run_file,progress,durations,main}.py` — `main` (626) is the second-longest function in the fork and becomes a `RunnerConfig` + phases; `run_tests_bundled.py` (54) → `scripts/test_runner/bundled/{bundles,scope,tally,run,main}.py` (shares `test_runner/` with the parallel runner — one owner for the summary printer, today duplicated); `generate_agent_runtime_stream_fixtures.py` (39) → `scripts/fixtures/stream/{normalize,frames,convergence,main}.py`; `scripts/ci/timings_report.py` (41) → `scripts/ci/timings/{fetch,stats,gantt,html,main}.py`; `doc_cite_adjacency.py` (48) → `scripts/doc_cites/{resolve,bounds,verdict,walk,main}.py`; `check-windows-footguns.py` (56) → `scripts/footguns/{rules,scan,main}.py` (the hyphenated filename stays as the entry — it is named by path in CI). Every script keeps its ≤ 60-line entry file so no CI or test invocation changes.

**T2** — `tests/_downstream/hermes_cli_conftest.py` (28) → `tests/_downstream/hermes_cli_fixtures/{fences,process_table,posix_gaps,web_prereqs,reporting}.py` with the conftest a ≤ 60-line importer (the 24 autouse fixtures are five families by their names); `tests/_downstream/id_markers.py` (35) → `tests/_downstream/id_markers/{vocabulary,posix,upstream_reds,narrowed,hooks}.py` — the 1,015 code lines are a DATA table of test ids; the module becomes `hooks.py` (≤ 60) + one data module per marker class, so the file a lane edits to add a marker is the data file, not the hook.

### 3.3 Landing protocol (09-21 §6, restated once, with the owner's two additions)

- **MOVE-only lands mechanically with hash proof.** A MOVE commit's moved spans are byte-identical: the lander re-derives each span's sha256 before/after from the sheet's line ranges (`git show <base>:<file> | sed -n a,bp | sha256sum` vs the new module's span) and pastes the table into the landing message; no review lane. (The launcher's ruling `move-only-lands-mechanically`, 2026-09-21.)
- **CHANGE commits carry a killing mutation**, named in the sheet, RUN on a throwaway copy, its red pasted, reverted — the 09-21 rule 3 positive control. A CHANGE that converts a ladder to a table names the mutation "swap two table entries → the named test reds".
- **One gate run per wave**, concurrently (09-21 §6.2 a–d, plus G5–G7). Touched tests only inside a lane.
- **Deletions** land under the dead-code queue's "Working a slice": delete + tombstone row in ONE commit, the `git grep` proof in the body, reintroduce → gate red → revert.
- **Findings file on arrival** into the domain queue (fork `CLAUDE.md` § Weakness escalation).

---

## 4. Helpers to unify (09-21 §5 re-verified by name, 2026-09-24)

Counts are `git grep "^def NAME(\|^    def NAME("` over the fork's production tree today. Every row: survivor · copies · lane.

| survivor | copies today | lane |
|---|---|---|
| `serde.safe_text` | 9 files (`board_store`, `child_events`, `events`, `parity`, `persona_chat_continuity`, `persona_profile_binding`, `running_work`, `snapshot`, `tool_turn_history`) | R1/R2 |
| `serde.read_json` | 6 (`board_store`, `mission_chat_steer`, `office_store`, `runtime_instances`, `serve_registry`, `store`) | R1 |
| `refusals.refusal` | 6 (`flow_graph_sync`, `level_sync`, `map_sync`, `mission_chat_workdir`, `persona_config_sync`, `harness_parts/gateway_commands`) — `tools/agent_chat_tool` is a seventh if T1 runs | R4 creates |
| `running_work/collect.row` | 5 (`discussions/attempt_store`, `discussions/native`, `gateway_peers`, `realm_sync`, `running_work`) | R2/R4 |
| `store_events.emit_store_event` | 4 `_emit` (`board_store`, `dispatch_store`, `office_store`; `serve.py`'s `_emit` is a frame writer, NOT this — named so nobody folds it) | R1 |
| **`clock.now_iso`** (new) | 4 `_now_iso` (`chat_live_log`, `peer_directory`, `serve_registry`, `serve_socket`) | R3 |
| `serde.positive_int` | 3 (`config`, `mcp_admission`, `profile_runner`) | R3 |
| `serde.safe_int` | 3 `_safe_int` (`mission_chat_turns`, `persona_chat_history`, `prompt_observability`) | R2 |
| `file_locks.try_lock_exclusive/unlock` | `persona_chat_continuity._try_lock/_unlock`, `mission_chat_turns._lock_fd_*`, **and `serve_socket._try_lock`** (new) | R2 creates, R1/R3 fold |
| `store_conflicts.guard_no_conflict` | 2 (`board_store`, `office_store`) | R1 |

The `_exists`/`paths.path_exists_safe`, `_pet_sheet_revision`/`_sheet_revision`, `_open_rgba`/`_as_rgba` rows of 09-21 §5 stand unchanged.

---

## 5. Dead code — where the list lives now

The rows are in `Harness_Brain/20 — Active Initiatives/dead-code-burn-down-queue.md` (launcher format: one line + pointer + evidence; "Working a slice" adapted so the deletion lands with its `git grep` proof in the commit body). The census that wrote them is §0.1's third instrument, run today over the 62: **36 top-level defs with no reference outside their own file**, of which **24 are `@method`-registered RPC handlers (false positives, struck)** and **12 are real rows** — the 09-21 §4.1 rows re-confirmed (`backfill_instance_profile_ids` 138, `fingerprint_home_capture` 23, `iter_fingerprint_paths` 5, `reset_unreadable_instance_rows` 12, `reset_runtime_resolve_cache` 5, `hud_field` 4, `volatile_hud_keys` 4, `active_workspace_lifts` 4) plus **four new**: `repo_context.repo_execution_context_for_task` 27 and `isolated_repo_context_for_run` 35 (tests only), `scripts/run_tests_parallel._split_discovery_roots` 3, `tests/_downstream/id_markers.ids_marked` 6. The three sheets add the rows a census cannot see (the eight `_cmd_gateway_*` trampolines, `build_parser`, `_cmd_persona_instance_detail`, `_cmd_persona_instance_archive`'s 2-line shim …). The 09-21 §4.2 argv census and §4.3 reach census (W0-D) are still owed and still Wave 0.

---

## 6. Doors — where a fork god file reaches into upstream, the door it should use

Per the scope rule; each sheet's § Doors carries the per-import table. The classes, from the DOORS read: **FIRST** (a door exists — use it, delete the reach), **NEAR** (a door exists, needs one widening — ledger row), **NO** (no door — ledger row, the reach stays, named). Summary for wave 1: `harness.py` — `agent.charsheet`/`agent.pet` (14 + 10 names) are FORK-ONLY modules living in an upstream directory (C1's files), so they are not doors at all; `hermes_cli.auth` × 6, `agent.credential_pool` × 4, `agent.account_usage` × 5, `hermes_cli.status*`, `runtime_provider`, `profiles`, `provider_catalog`, `nous_account`, `models` are read-only imports of PUBLIC names (FIRST: keep, but through ONE fork adapter module `harness_parts/_upstream_doors.py` so the surface the merge can break is one file, not thirty import lines); `serve.py` — `tools.process_registry` (the 2026-09-24 `notify_on_complete` ruling: FIRST), `agent.ssl_guard`, `agent.process_bootstrap`, `hermes_cli.config` (FIRST, public); `persona_commands.py` — `tools.registry`, `tools.terminal_tool_lifecycle`, `gateway.session_context`, `agent.title_generator`, `hermes_cli.flag_binding` (FIRST, public). **No wave-1 file needs a widening.** The `_upstream_doors.py` adapter is a rule-16 module (layer: wiring) and W0-G6's "no `_private` import from upstream" arm is what keeps it honest.

---

## 7. What the operator owes (09-21 §7, unchanged) — plus the questions in §9

1. One boot on the H4 build. 2. The §4.2 argv rulings where the launcher still lowers a verb. Everything else is decided by the lane and its sheet review.

## 8. Ledger (re-cut for 62 + C1/T1; `[ds-size]` counts by RAW until Q1)

| lane | files | status | MOVE | CHANGE | `[ds-size]` after |
|---|--:|---|---|---|--:|
| W0 | — | **DONE** `7425b754a7` | — | 1 | code 40 / 73,870 |
| H1 | 8 | **DONE** `73201f631e` | — | 2 | 40 / 73,803 |
| S1 | 1 | planned | 1 | — | — |
| H4 | 1 | **DONE** `d567f07f62` (sheet `serve.md`) | 1 | 4 | 39 / 69,761 |
| H3 | 1 | **DONE** `d0639591b0` (sheet `persona_commands.md`) | 1 | 1 | 39 / 67,503 |
| H2 | 2 | **DONE** `bf4377f226` (sheet `harness.md`; `runtime_commands` split still owed — runtime-queue row) | 1 | 5 | **37 / 58,300** |
| R1 | 7 | Wave 2 batch 1: sheets `persona_assignments.md`, `office_store.md` (G1) | 2 | 2 | 35 |
| R2 | 15 | Wave 2 batch 1: sheets `prompt_observability.md`, `persona_chat_history.md` (G2) | 2 | 2 | 33 |
| R3 | 16 | Wave 2 batch 1: sheets `serve_rpc.md`, `serve_socket.md`, `core_cache.md`, `profile_runner.md`, `snapshot.md` (G4) | 5 | 5 | 28 |
| R4 | 10 | Wave 2 batch 1: sheet `realm_sync.md` (G3) | 1 | 1 | 27 |
| C1 · T1 | 2 · 2 | planned (Q2: yes) | 1 · 1 | 1 · 1 | 27 (the four are outside the 62 count) |
| S2 | 7 | planned | 1 | 1 | 20 |
| T2 | 2 | planned | 1 | — | 18 |

The `[ds-size] after` column now carries the CODE counter (ruling Q1) — units, and for the landed lanes the total; the 18 remaining R1–R4 files of the second batch and the S/T/C lanes take it to 0. Wave 1 spent nine CHANGE commits where the plan budgeted four, each with its red recorded — the count that matters is commits per RED, not per lane, and it stayed one.

Fourteen lanes, ≤ 29 commits (plus ≤ 1 `style:` per lane), for 66 files.

## 9. Owner questions — RULED 2026-09-24 (Tony)

**Rulings:** Q1 **CODE lines** bind the ceiling (ADR 0007 stands unamended; the `[ds-size]` gate counts code lines only, so the program's ceiling population is the 34 files over by code, and the 28 over by raw alone are in scope for legibility work but not for the ceiling gate — Q3 is therefore moot for `patch_coverage.py`-class files: they are under the ceiling; relocate history where a sheet says so, never split them). Q2 yes. Q3 relocate history, no split. Q4 gate. Q5 one per package. Lanes apply these as facts.

1. **Which counter binds the ceiling — raw lines (the owner's list, 62) or code lines (ADR 0007, 34)?** Recommend **raw** (a comment is a reader's cost too, which is the docstring argument of 09-21 §0.1 taken to its end), with ADR 0007 amended by one line; the gate prints both until then.
2. **Do the four fork-only files in `agent/charsheet/` and `tools/` (C1, T1) stay in the program?** Recommend **yes** — they are fork code by the fence, and their new modules go under `agent/charsheet/` (already a fork-only package) and a new `tools/agent_chat/` package, never a top-level upstream file.
3. **`patch_coverage.py`-class files (over by raw, under 400 code):** split, or relocate comment history per rule 7 and stop at ≤ 800 raw? Recommend **relocate history, no split** — a split of 385 code lines manufactures modules.
4. **Function floor 150 / nesting 4 (rule 17):** bind as a gate, or as a review criterion only? Recommend **gate**, grandfathered shrink-only — a criterion nobody measures is the failure the launcher's ratchets exist to stop.
5. **`_upstream_doors.py` (§6):** one adapter module per fork package, or one for the fork? Recommend **one per package** (`harness_parts/`, `agent_runtime/`), since W0-G6 walks per package and a merge break then names its package.

---

## Appendix A — the probe (Wave 0 lands it as `scripts/god_file_probe.py`; run today from a scratch copy)

```python
# python god_probe.py <repo_root> [--min-lines 800] [--detail FILE ...]
# Per file: raw, code (non-blank, not '#'-led), top-level defs, longest fn, if-chains>=3 arms
# (an If not itself an orelse arm; arms = 1 + elif count + (1 if a trailing else)), of which
# routed = an arm test compares to a str constant / str tuple, or calls isinstance();
# str== = Compare nodes with a str-constant comparator; isinstance = Call nodes to isinstance.
import ast, subprocess, sys
def code_lines(src): return sum(1 for l in src.splitlines() if l.strip() and not l.strip().startswith("#"))
def routed(test):
    for n in ast.walk(test):
        if isinstance(n, ast.Compare) and any(isinstance(c, ast.Constant) and isinstance(c.value, str)
            or isinstance(c, (ast.Tuple, ast.Set, ast.List)) and any(isinstance(e, ast.Constant)
            and isinstance(e.value, str) for e in c.elts) for c in n.comparators): return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "isinstance": return True
    return False
def chains(tree):
    orelse = {id(o) for n in ast.walk(tree) if isinstance(n, ast.If) for o in n.orelse if isinstance(o, ast.If)}
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and id(n) not in orelse:
            arms, r, cur = 1, routed(n.test), n
            while len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
                cur = cur.orelse[0]; arms += 1; r = r or routed(cur.test)
            arms += bool(cur.orelse)
            if arms >= 3: out.append((n.lineno, arms, r))
    return out
```

The 2026-09-24 run over the 62 (the full script, with the def-map `--detail` mode and the table printer) is reproduced by the field notes' scratch copy; its output is §0.2 verbatim.
