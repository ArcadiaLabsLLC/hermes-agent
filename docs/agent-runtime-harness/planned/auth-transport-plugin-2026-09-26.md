# Auth transport → plugin surface (design sheet, lane AUTH-DESIGN, 2026-09-26)

Executes the runtime-queue § Seams row "the auth-transport edits in eight upstream files want a
plugin-surface home" (owner ruling 2026-09-26: bring it to the plugin; the ACP carry is dropped
instead). Rules: [`harness-plugin-and-upstream-seams.md`](harness-plugin-and-upstream-seams.md) §1
(rules 1–3, 9, 10). Ratchet: `[up-fp] files=178 deleted_lines=924 heavy=4` at base `067fa1a257`
(live, measured this sitting). Numstats below are `git diff --numstat 067fa1a257 HEAD`.

## 1. What the three commits changed, and the wire the launcher reads

| commit / file | one line | ratchet (added/deleted) |
|---|---|---|
| `98f8a8caf9` `hermes_cli/auth.py` | `persist_provider_login(provider_id, state)` = `_persist_provider_state_to_store(…, _auth_file_path(), set_active=False)` | 13/1 → **18/1** |
| `…` `auth_codex.py` | `_codex_device_code_login(*, on_verification=None)` fires `(issuer/codex/device, user_code)`; `login_codex_account(on_verification, *, flow)` saves with `set_active=False` | new **11/1** |
| `…` `auth_codex_browser.py` | `_codex_browser_login(…, on_verification=None)` fires `(auth_url, "")` | new **4/1** |
| `…` `auth_minimax.py` | `_minimax_oauth_login(…, on_verification=None, persist=True)`; `login_minimax_account` persists without activating | new **14/2** |
| `…` `auth_nous.py` | `login_nous_account`: guest → `anon_auth.run_sign_in()` (canonical upgrade), else `_nous_device_code_login(on_verification=)` + `persist_provider_login` + pool sync | 2/1 → **22/1** |
| `…` `auth_xai.py` | `_xai_oauth_device_code_login(…, on_verification=None)`; `login_xai_account` persists `auth_mode=oauth_device_code` without activating | new **13/1** |
| `…` `provider_catalog.py` | `provider_login_catalog()` rows gain `browser_login`, `browser_login_methods` | 189/0 → 192/0 (199/0 after the 09-25 merge) |
| `…` `subcommands/auth.py` | `auth login --flow {browser,device_code}` | 35/0 → **37/0** |
| `…` fork-only | `hermes_cli/provider_browser_login.py` (new, 90 lines: driver table, NDJSON emit, stdout/stderr discard, error-code map); `auth_noninteractive.auth_login_command` routes supported providers to it under `set_hermes_home_override`; `tests/hermes_cli/test_provider_browser_login.py` (132) | zero |
| `38f9345633` `harness_parts/provider_visibility.py` | `auth_logins[]` rows gain `id` (`nous`, `openai-codex`, `qwen-oauth`, `minimax-oauth`) | fork-only, zero |
| `09d722bb30` docs | qualification record + queue rows | zero |

**The wire the launcher depends on** — `EterniaLauncher/packages/agents/eternia_hermes_adapter/lib/src/providers/`:
- `provider_connections.dart:41` builds argv `auth set-key <provider> --stdin [--label]`, reads the JSON ack; the login stream reads NDJSON `event` ∈ `code|pending|done|error` with `verification_uri`, `user_code`, `code`, `cli_command`, `home` (`:195–232`; `flow_not_wrapped || unsupported_flow` both mapped).
- `provider_parse.dart:54` reads catalog `browser_login` / `browser_login_methods` (`browser`, `device_code`); `:215–230` reads `auth_logins[].id|name|logged_in`.
- Spellings `auth set-key` / `auth login` and every key above are FIXED by this sheet; nothing here changes the wire.

## 2. Per hunk, one verb

Upstream doors checked (rule 10 order): `VALID_HOOKS` (`hermes_cli/plugins.py:108–203`, none fires in a CLI auth verb; `pre_command` is REPL/gateway slash only) · `VALID_MIDDLEWARE` (`middleware.py:24`: tool/LLM request+execution only) · `register_cli_command` (`plugins.py:663`: TOP-LEVEL `hermes <name>` only) · `register_command` (`plugins.py:677`: in-session `/slash`, not argv) · call parameters: `_nous_device_code_login(on_verification=)` and `step_up_nous_billing_scope(on_verification=)` EXIST upstream (`auth_nous.py:1350–1395`); codex/xai/minimax flows have none · PR #124190 (`up/store-home-override`, `692d48b985`): `get_store_home("auth")` — retires `auth.py`'s HOME hook row, not this batch.

| # | hunk | verb | binding / shape / reason |
|---|---|---|---|
| H1 | `auth.py` `persist_provider_login` (+5) | **PLUGIN** | move to fork-only `hermes_cli/provider_browser_login.py` as `_persist(provider_id, state)` calling `_persist_provider_state_to_store(provider_id, state, _auth_file_path(), set_active=False)` (upstream `auth.py:808`, public-enough for a fork-only module; the plugin dir is fenced, see Q1). `auth.py` 18/1 → 13/1 |
| H2 | `auth_codex.py` `login_codex_account` (+8) | **PLUGIN** | move into the transport's `_codex` driver: `state = _codex_browser_login(open_browser=False, on_verification=v)` or `_codex_device_code_login(on_verification=v)`; `_save_codex_tokens(state["tokens"], last_refresh=…, set_active=False)` (`set_active` exists upstream, `auth_codex.py:174`) |
| H3 | `auth_codex.py` `on_verification` kwarg + fire (+3/−1) | **PR** | PR-1 (below). Fork line after merge: none |
| H4 | `auth_codex_browser.py` kwarg + fire (+4/−1) | **PR** | PR-1 |
| H5 | `auth_minimax.py` `login_minimax_account` (+6) | **PLUGIN** | move into `_minimax` driver: `_minimax_oauth_login(open_browser=False, on_verification=v, persist=False)` then `_persist("minimax-oauth", state)` |
| H6 | `auth_minimax.py` `on_verification` + `persist` kwargs (+8/−2) | **PR** | PR-1. `persist=False` is required: upstream persists as ACTIVE via `_save_active_provider_state` (`auth_minimax.py:161`), and the owner's rule is no inference-selection writer |
| H7 | `auth_nous.py` `login_nous_account` (+20) | **PLUGIN** | move into `_nous` driver unchanged: `anon_auth.current_nous_state/is_guest_state/run_sign_in/Code` are upstream-public (`anon_auth.py:161,180,1084`; `anon_sign_in.py:92`), `_nous_device_code_login(on_verification=)` upstream, `_sync_nous_pool_from_auth_store` upstream. **No PR.** `auth_nous.py` 22/1 → 2/1 (the G6 `inference_base_url` row stays, its own PR) |
| H8 | `auth_xai.py` `login_xai_account` (+6) | **PLUGIN** | move into `_xai` driver: `_persist("xai-oauth", {**state, "auth_mode": "oauth_device_code"})` |
| H9 | `auth_xai.py` `on_verification` kwarg + fire (+6/−1) | **PR** | PR-1 |
| H10 | `provider_catalog.py` `browser_login*` (+3) | **PLUGIN** | decorate in fork-only `harness_parts/provider_visibility.py::_provider_visibility_login_catalog` (`:148–154`, the only producer the launcher reads): `{**row, "browser_login": supports_browser_login(id), "browser_login_methods": browser_login_methods(id)}`. `auth_noninteractive._login_flow_for` reads `flow`/`cli_command` only — unaffected. 199/0 → 196/0 |
| H11 | `subcommands/auth.py` `--flow` (+2) | **CARRY → PR** | rides with the `set-key`/`login` sub-parsers (35/0) and `auth_commands.py` dispatch (7/0): no door for a sub-verb on a builtin parser; retiring event = PR-2 merged |
| H12 | `harness_parts/provider_visibility.py` `id` | — | fork-only; nothing to move |

**PR-1 — "out-of-band verification callback on the remaining device/browser flows"** (upstream branch `up/auth-on-verification`, ~14 lines + 2 invariant tests). Mirror `_nous_device_code_login`'s existing shape (`auth_nous.py:1354, 1388–1391`: `on_verification: Optional[Callable[[str, str], None]] = None`, fired AFTER the print/browser block and BEFORE polling, under `suppress(Exception)`):
- `auth_codex.py:1104` `_codex_device_code_login(*, on_verification=None)`; fire `(f"{issuer}/codex/device", user_code)` before `_codex_poll_authorization_code` (3 lines).
- `auth_codex_browser.py:110` `_codex_browser_login(…, on_verification=None)`; fire `(auth_url, "")` after `auth_url` is built (3 lines).
- `auth_xai.py:555` `_xai_oauth_device_code_login(…, on_verification=None)`; fire `(verification_uri_complete or verification_uri, user_code)` after `_print_device_code_instructions` (4 lines).
- `auth_minimax.py:167` `_minimax_oauth_login(…, on_verification=None, persist=True)`; fire after the code print; `if persist: _minimax_save_auth_state(auth_state)` (4 lines).
Fork after merge: the four `def` lines and fires are upstream's; the fork's callers pass `on_verification=` — zero fork lines in those files. Until merge the kwargs are the CARRIED interim (they already are; reasons rows updated, not raised). Upstream pitch: the TUI gateway is the same consumer Nous already serves (its own comment, `auth_nous.py:1387`).

**PR-2 — "plugin CLI sub-verbs on a builtin parser"** (`up/plugin-cli-parent`, ~8 lines + 1 test):
- `plugins.py:663` `register_cli_command(…, parent: str | None = None)`; entry gains `"parent": parent` (2 lines).
- `subcommands/auth.py:8` `build_auth_parser` returns `auth_subparsers` (1 line); `main.py:3439` stores it: `_BUILTIN_SUBPARSERS["auth"] = build_auth_parser(…)` (2 lines).
- `main.py:3347` `_attach_plugin_cli_command`: `target = _BUILTIN_SUBPARSERS.get(cmd_info.get("parent")) or subparsers` (2 lines); `_plugin_cli_discovery_needed` (`:2886`) also true when `first == "auth"` and a manifest declares `parent: auth` (1 line, via the fork's already-landed `discover_declared_cli_commands` path; upstream's discovery-gate PR is the same seam).
- argparse: a sub-subparser's `set_defaults(func=…)` overrides `auth_parser.set_defaults(func=cmd_auth)` (`subcommands/auth.py:86`), so `auth_commands.py`'s 7-line dispatch vanishes with the parsers.
Fork after merge: `plugins/eternia-harness/plugin.yaml` `cli_commands:` gains `- {name: set-key, parent: auth}` and `- {name: login, parent: auth}`; `__init__.py::register` calls `ctx.register_cli_command("set-key", parent="auth", setup_fn=…, handler_fn=auth_set_key_command)` and the same for `login` (setup = today's argument blocks, moved verbatim into `hermes_cli/auth_noninteractive.py`). Launcher argv unchanged. `subcommands/auth.py` 37/0 → 0, `auth_commands.py` 7/0 → 0.

## 3. Exec lanes (raw lines), landing order, `[up-fp]` arithmetic, killing mutations

Order: **L1 → L2 → L3**, PRs serial (seams §3). L1 has no dependency and lands today; L2/L3 land in the fork only at the weekly merge that carries each PR (or on the decline fallback, Q5).

| lane | raw lines | does | `[up-fp]` before → after | killing mutation (state it, apply, record red, revert; record the red in the commit message) |
|---|---|---|---|---|
| **L1 AUTH-MOVE** (Opus, one worktree) | ~300 (45 out of 5 upstream files; +50 in `provider_browser_login.py`; +6 in `provider_visibility.py`; `test_provider_browser_login.py` 132 re-pointed, 2 positive controls added) | H1, H2, H5, H7, H8, H10. One MOVE commit per upstream file (hash in message), one CHANGE commit for the transport + tests. `upstream-footprint-ledger.md` rows + fixture `reasons` row in the same landing | `files 178 → 178`, `deleted_lines 924 → 924`, `heavy 4 → 4` — honest: the moves lower ADDED only (`auth.py` 18→13, codex 11→3, minimax 14→8, nous 22→2, xai 13→7, catalog 199→196); the ratchet counts files and deletions, and neither moves until PR-1. The fixture is NOT edited except its `reasons` row (the gate reds on a lowered-tree-unlowered-fixture only for the three numbers) | (a) in `_persist`, `set_active=False` → `True`: `test_real_drivers_persist_a_b_a_without_switching_models` must red (it asserts the active provider is unchanged after A/B/A). (b) drop the `browser_login` decoration in `provider_visibility.py`: `test_catalog_advertises_only_real_machine_methods` must red — re-point that test at `_provider_visibility_login_catalog()` FIRST or it is asserting about nothing (capture-is-a-vehicle) |
| **L2 AUTH-PR1** (Opus) | ~40 upstream (14 src + 2 tests) + fork adoption ~20 | open PR-1 on `upstream/main` (`f077152871` at this sitting); on merge, the weekly merge deletes the fork's four kwarg hunks (H3, H4, H6, H9) and the transport passes `on_verification=` to upstream's | `files 178 → 174` (`auth_codex.py`, `auth_codex_browser.py`, `auth_minimax.py`, `auth_xai.py` reach 0/0), `deleted_lines 924 → 919`, `heavy 4 → 4` | PR test: delete the `on_verification(...)` fire in one flow → the test's recorded callback list is empty → red. Fork side: `test_wire_has_one_terminal_and_never_serializes_helper_output` must red if the driver stops passing the callback (no `code` event) |
| **L3 AUTH-PR2** (Opus) | ~25 upstream (8 src + 1 test) + fork ~60 (parser blocks move to `auth_noninteractive.py`, `plugin.yaml` + `register` rows, `auth_commands.py`/`subcommands/auth.py` hunks deleted) | open PR-2; on merge, fork deletes H11 + the `set-key`/`login` parsers + the 7-line dispatch, registers both from the plugin | `files 174 → 172`, `deleted_lines 919 → 919`, `heavy 4 → 4`. `scripts/dump_cli_contract.py --check` byte-identical (`auth set-key`/`auth login --help` unchanged) | PR test: register `parent="auth"` and assert `hermes auth <name> --help` parses; mutate `target = subparsers` (ignore `parent`) → red. Fork: the launcher's argv `['auth','set-key',p,'--stdin']` run through `main()` must exit 0 with a JSON ack; `parent:` dropped from the manifest row → argparse error → red |

Not this lane: `auth.py` 13/1 (HOME hook) → 0 when PR #124190 merges and the fork adopts `get_store_home("auth")` (ledger row, HOME-PR); `auth_nous.py` 2/1 (G6). After all four: `files 172 → 170`.

Landing gates per lane (once, at the landing, not per commit): `tests/hermes_cli/test_provider_browser_login.py`, `tests/hermes_cli/test_auth_noninteractive.py`, `tests/hermes_cli/test_provider_visibility_identity.py`, `tests/tooling/test_plugin_imports_public_surface.py`, `tests/scripts/test_upstream_footprint.py`, `scripts/check_compat_pointers.py`, `scripts/dump_cli_contract.py --check`. The launcher is read-only for all three lanes; no adapter change.

## 4. Open questions — decided

| # | question | default (decided) |
|---|---|---|
| Q1 | Does the transport move INTO `plugins/eternia-harness/`? | **No — it stays the fork-only `hermes_cli/provider_browser_login.py`.** Rule 3's fence (`test_plugin_imports_public_surface.py`) forbids the plugin dir importing `_private` upstream names, and every driver needs one (`_codex_device_code_login`, `_xai_oauth_device_code_login`, `_minimax_oauth_login`, `_nous_device_code_login`, `_persist_provider_state_to_store`). A fork-only module in `hermes_cli/` is ratchet-neutral and unfenced. Retiring event: upstream exposes public callback-bearing login entry points (a wrapper PR is exactly what the rubric rejects, so it is not proposed). The plugin reaches it only through PR-2's `handler_fn`. |
| Q2 | Interim for H3/H4/H6/H9 while PR-1 is open? | **Keep them carried as today**; L1 updates the fixture `reasons` rows to name PR-1 as the retiring event. No runtime patch of `_print_device_code_instructions` (`auth_device_flow.py:289`) to avoid the PR — that is a second door (rule 10) and it cannot reach codex device (inline print) or codex browser (no code) anyway. |
| Q3 | PR-2 spelling: `parent=` on `register_cli_command`, or a new `register_cli_subcommand`? | **`parent=` on the existing call** (rule 10: first door, one small widening; no second registrar). Manifest row spelling `parent: auth`. |
| Q4 | Where do `--flow` and the other login/set-key arguments live after PR-2? | **`hermes_cli/auth_noninteractive.py`** (`add_auth_login_arguments(parser)` / `add_auth_set_key_arguments(parser)`), the file that already owns both verbs; `subcommands/auth.py` returns to upstream's bytes. |
| Q5 | PR-1 or PR-2 declined? | PR-1 declined → the four kwarg hunks become RULED carry rows (reason: "additive callback parameter, replaces the def line only; upstream declined <link>"), `[up-fp]` stays at 178/924 and the sheet's L2 arithmetic is struck. PR-2 declined → `auth set-key`/`auth login` stay carried (37/0 + 7/0) under the existing ledger rows; the launcher does NOT move to a `harness auth …` spelling (owner: spellings stay). Neither decline reopens this sheet. |
| Q6 | Does `38f9345633` (`auth_logins[].id`) need anything? | **No.** Fork-only file; the launcher already reads `id` with `name` fallback (`provider_parse.dart:223`). |
| Q7 | Haiku for any of this? | **L1's per-file MOVE commits only** (verbatim relocation, hash in message); the transport CHANGE, both PRs and every test are Opus. |
