# Planned — the chat turn's prompt surface, lane h-prompt-design (2026-10-05): what the ~22k input tokens are made of, and what to cut

**Status:** DESIGN 2026-10-05 (Fable, read-only against the live store, the neko / gpt-launcher `agent.log`, the recorded first requests in `prompt_observability_archive/`, and the tree). No production code was changed. **Row:** the `TAKEN … lane h-prompt-design` row under `Harness_Brain/20 — Active Initiatives/runtime-queue.md` § "Filed on arrival — 2026-10-05 (owner live turns)". **Owner doc:** [`../05-chat-turn-lane.md`](../05-chat-turn-lane.md) §4 (tool posture), §4c (the declared toolset), §5 (MCP admission), §10 (provider dispatch). **Siblings:** `planned/turn-latency-h-turn1-2026-10-05.md` (the first-turn cost this surface is one leg of); `planned/chat-turn-prep-cost.md` (the pre-admit span).

**One sentence.** Of Neko's 21,957 metered first-turn tokens, about 17k are `tools[]` — four promoted `launcher_qa` MCP tools (5.3k) and twenty-three Hermes built-ins (8.2k) of which sixteen were never called on any recorded persona-chat turn — and about 7.6k are the system prompt (an upstream foundation 2.1k, the fork's operative rules 2.1k, a 96-entry skills index 1.9k the persona's own declaration would cut to nine); the per-turn history is small (~330 tokens/turn) and 94–98 % of each later turn is already cache-hit, so the saving is on the FIRST turn of every chat — which is 37 % of all persona-chat turns on record — and the one lever that beats shrinking is letting that first turn hit the previous chat's cached prefix.

---

## 0. Ground truth

### 0.1 The two recorded first requests

The runtime records every chat turn's redaction-safe final model input (`agent_runtime/profile_runner/model_input_observability.py`, record key `final_model_input`): the full system message, the user message, the tool NAMES and the tools' JSON byte count. The system and user texts below are tokenized from those records; the tool schemas were rebuilt in-process (`model_tools.get_tool_definitions(["hermes-cli"], skip_tool_search_assembly=True)` + the profile's `cache/mcp_schema_cache.json` + the fork's plugin schemas, assembled through `tools.tool_search.assemble_tool_defs`) and tokenized the same way. Tokenizer: `tiktoken` `o200k_base` on the compact JSON (`separators=(",", ":")`); the provider meters its own wire form, so the tool column over-reads by ~10 % (24.7k tiktoken vs 21,957 metered for Neko; the Responses form drops the `{"type":"function","function":{…}}` wrapper).

| | Neko `ctx_96cd09894da6e457` (neko, `gpt-5.6-luna`, "hi", 19:16:23) | Launcher Dev Agent `ctx_f4541938a64e4189` (gpt-launcher, `gpt-6-luna-900k`, "hi", 19:20:59) |
|---|---|---|
| metered `in=` (API call #1, no cache) | **21,957** | **35,994** |
| system message (3 sections, tiktoken) | 7,647 | 12,107 |
| user message (HUD; + skill preload on dev) | 484 | 377 |
| `tools[]` (31 entries, tiktoken on JSON; recorded `json_bytes`) | ≈16,580 (76,436 B) | ≈16,880 (78,750 B) |
| history | 0 | 0 |
| `tool_search activated` log line | 28 core/visible kept, **51 deferred (~20,232)**, listing full (budget 4,000) | 28 kept, **69 deferred (~25,148)**, listing full |
| later turns (`cache=`) | 94–98 % hit, `in` grows ≈330/turn | 97 % hit |

### 0.2 Composition, Neko, ranked by tokens (what the 21,957 is made of)

| # | part | tokens | owner | used on recorded persona-chat turns? (§0.3) |
|---|---|---|---|---|
| 1 | `tools[]`: 4 promoted `launcher_qa` MCP tools — `open_app_tab` 2,087 · `launch_or_attach` 1,515 · `screenshot_window` 1,019 · `capture_screenshot` 640 | **5,261** | `tools/tool_search_downstream.py::_MCP_NEVER_DEFER_VERBS` (fork) + the server's own descriptions | `open_app_tab` 11 (via `tool_call`, pre-promotion), `launch_or_attach` 3, `screenshot_window` 2, `capture_screenshot` 0 |
| 2 | `tools[]`: 23 Hermes built-ins — `terminal` 1,012 · `delegate_task` 967 · `skill_manage` 783 · `browser_exec` 775 · `memory` 768 · `execute_code` 745 · `search_files` 500 · `clarify` 371 · `read_file` 284 · `web_extract` 242 · `browser_vault_list` 240 · `write_file` 234 · `patch` 202 · `skill_view` 197 · `browser_vault_save_login` 195 · `browser_vault_fill` 189 · `vision_analyze` 188 · `browser_vault_enter_code` 183 · `web_search` 178 · `browser_vault_unlock` 118 · `skills_list` 60 | **8,243** | upstream schemas; the chat-lane set is `harness_core` (§4c) with the T3/T6a cost policy BYPASSED under `unbounded` (doc 05 §4) | called: `terminal` 24, `search_files` 13, `read_file` 11, `skill_view` 5, `skills_list` 1. **Never called (16 tools, ≈5,940 tokens):** `delegate_task`, `skill_manage`, `browser_exec`, the five `browser_vault_*`, `memory`, `execute_code`, `clarify`, `web_extract`, `web_search`, `write_file`, `patch`, `vision_analyze` |
| 3 | system — the fork's Mission Control operative rules (`_mission_chat_operative_rules`) | **2,088** | `agent_runtime/mission_chat_prompts.py` (fork) | — (rules) |
| 4 | system — upstream stable foundation: identity 269, `# Finishing the job` 152, `# Parallel tool calls` 344, `# Tool-use enforcement` + its five tags 175+89+179+105+65, `Before finalizing` 110, `<external_state_verification>` 138, `<missing_context>` 80, `# Async handoff` 343, steering 72+87, skill safety 75 | **2,127** | `agent/prompt_builder.py` (upstream) | — |
| 5 | system — `## Skills` + `<available_skills>` index: **96 entries**, every category (creative, baoyu-comic, cozy-alice-image, …) | **1,853** (+209 header) | upstream `_render_skills_index`; the persona declares **9** skills (`agent_runtime.personas.neko_supervisor.skills`) | `skill_view` 5 calls |
| 6 | `tools[]`: bridge trio — `tool_search` 1,414 (of which the embedded deferred listing is 981: 51 names + ≤60-char descriptions) · `tool_call` 198 · `tool_describe` 103 | **1,715** | upstream `bridge_tool_schemas`; fork `tool_describe_schema` | `tool_call` 43, `tool_describe` 21, `tool_search` 9 — the most-used tools on the lane |
| 7 | `tools[]`: fork plugin tools — `agent_chat_send` 772 · `skill_search` 212 · `agent_chat_dispatches` 187 | **1,171** | `tools/agent_chat/schemas.py`, `plugins/eternia-harness` (fork; `_BUILTIN_NEVER_DEFER`) | 0 calls on record (the Mission Lead's one named capability; keep) |
| 8 | system — `# Hermes runtime environment` (host, cwd, scratch, the Windows shell paragraph) | **496** | upstream `system_prompt.py` | — |
| 9 | user turn — `<runtime_context>` Runtime Situation HUD (board, capability envelope, installs, roster) | **482** per turn, uncached by design | `agent_runtime/persona_runtime.py::_mission_chat_user_message` (fork) | — |
| 10 | system — persona identity 90 + SOUL.md 371 (neko) · plugin sections `tool-guidance` 153 + `windows-tooling` 291 · profile line + memory headers ≈240 | **≈1,150** | fork / profile-owned | — |

Dev Agent differs in three places only: SOUL.md is 3,400 tokens (its `## Anti-sprawl` block alone is 2,492), MEMORY.md + USER.md are injected (3.6 KB), and the skills index is 3,711 tokens (the gpt-launcher profile's 98 KB `.skills_prompt_snapshot.json`); the listing is 1,261 (69 deferred: + `dart` 18). Its tools are the same 31.

### 0.3 What the agent actually calls on the persona-chat lane

`profiles/base/state.db` (the serve's HERMES_HOME holds every `persona_chat_*` session), `messages.tool_calls` since 2026-09-20: **64 operator turns over 24 chats** (2.7 turns per chat — so a first, uncached turn is 37 % of all turns). Calls: `tool_call` 43 → `mcp__launcher_qa__…open_app_tab` 11, `get_runtime_state` 5, `launch_or_attach` 3, `screenshot_window` 1, `get_auth_state` 1, `process_manage` 3, `todo_list` 1, QA build/job verbs ≈6; `terminal` 24; `tool_describe` 21; `search_files` 13; `read_file` 11; `tool_search` 9; `skill_view` 5; `skills_list` 1. Everything else in the 31: zero. The four promoted `launcher_qa` verbs show zero DIRECT calls because their promotion landed the same day (lane h-defer, 2026-10-05); every earlier reach went through the bridge, which is the cost the promotion retired (two round trips per screenshot turn).

For contrast, the worker lane (`profiles/alice/state.db`, 438 turns): `read_file` 519, `terminal` 440, `search_files` 346, `patch` 157, `tool_call` 157 (`process_manage` wait/poll 114), `skill_view` 143, `execute_code` 69, `write_file` 46, `vision_analyze` 39, `delegate_task` 7, `clarify` 2. The worker lane is NOT this plan's scope; its numbers say which tools a DEV persona's chat lane must keep eager (`patch`, `write_file`, `execute_code`) that a SUPERVISOR's need not.

### 0.4 Where the cost lands (latency, not only tokens)

- Turn 1 of every chat is sent with no cache hit (`API call #1 … in=21957` carries no `cache=`; every later call reads 94–98 %). The codex transport keys the cache on `sha256(instructions + tools)` **scoped by the chat's session id** (`agent/auxiliary_client.py` → `agent/transports/codex._cache_scope_from_session_id(_runtime_main_value("cache_scope") or session_id)`; the record says `cache_scope_source = cache_scope_id`, `prompt_cache_key_source = static_prefix`, and the session header fingerprint equals the client request header fingerprint). Two chats of one persona on one profile send byte-identical instructions + tools (the HUD and the skill preload ride the user turn precisely so the prefix is stable, `_mission_chat_surface_message` T5/T9a) and still never share a bucket.
- The visible latency of the uncached first call versus a cached later one, from the same chat's ledgers: `request_sent → response_headers` 2.9 s on turn 1 (18:51 chat, in the h-turn1 plan §0.1) against 1.0–1.2 s on turns 2–3 of the 19:16 chat. That 1.7 s is prefill + the first connection; the split is UNVERIFIED (the one read: a turn-1 ledger with `builds_overlapped = 0` and `tls_done − client_built < 50 ms`, which no record yet has — the h-turn1-tail lane owns the preconnect half).
- Tokens → latency is weak on these models: the Dev Agent's uncached 35,994-token first call answered in 1.8 s; Neko's 21,957 in 4.2 s with a core build overlapping. Shrinking the surface buys prefill on the uncached turn only, and a smaller cache-miss cost; the cached turns gain ≈0.

---

## 1. Stages

Order: S0 and S6 are independent of each other and of the rest; S1 → S2 → S3 → S4 is the token order (largest, cheapest-to-prove first). Every stage is hermes-side; S2 names a launcher-side row. All upstream files are left as they are: every change lands in a fork module or a profile `config.yaml`.

### S0 — the per-part receipt (measurement before cutting)

- **Goal:** every first turn's record says what its tokens are made of, so S1–S4 land against a number and the next lane does not re-derive §0.2 by hand.
- **Touches:** `agent_runtime/profile_runner/model_input_observability.py` (fork): beside `tool_schema.json_bytes`, a `tool_schema.per_tool_chars: {name: chars}` map and a `system_prompt_sections[*].blocks` list of `(heading, chars)` for the `#`/`##`/`<tag>` blocks; one log line per first turn, `prompt_surface tools=<n> tool_chars=<n> promoted_mcp_chars=<n> listing_chars=<n> system_chars=<n> skills_entries=<n> hud_chars=<n>`. Chars, not tokens: the record must not depend on a tokenizer the venv does not ship (`tiktoken` is absent from `~/.venvs/hermes-test`); the chars/4 rule upstream uses (`tools/tool_search.py::estimate_tokens_from_schemas`, `CHARS_PER_TOKEN`) is the stated basis.
- **Positive control:** a record built from a fixture tool list with one 2,000-char description shows that name at the top of `per_tool_chars`; plant = drop the map → `tests/agent_runtime/test_prompt_observability.py` red.
- **Saving:** 0 tokens; it is the gate every later stage's commit body cites.

### S1 — the chat lane defers what the lane never calls (config first, knob second)

- **Goal:** the sixteen never-called built-ins leave the eager array on the supervisor's chat lane and ride the bridge listing like `process_manage` does today.
- **Mechanism (no code):** `tools.tool_search.defer` in the persona's bound profile `config.yaml` (neko: `X:/Eternia/.hermes/profiles/neko/config.yaml`). The key the loader reads is `tools.tool_search.*` (`tools/tool_search.py::_config_from_loader` → `hermes_cli.config.load_config()["tools"]["tool_search"]`); the `agent.tool_search:` block both profiles carry (`threshold_pct: 10`, `max_search_limit: 20`) has NO reader anywhere in `hermes_cli/`, `agent/`, `agent_runtime/` or `tools/` (grepped) — dead text, delete it in the same config edit. The list REPLACES the curated default wholesale (`ToolSearchConfig.from_raw`), so it is the curated 17 plus: `browser_exec`, `browser_vault_list`, `browser_vault_unlock`, `browser_vault_fill`, `browser_vault_save_login`, `browser_vault_enter_code`, `memory`, `execute_code`, `delegate_task`, `skill_manage`, `vision_analyze`, `web_search`, `web_extract`. `is_deferrable_tool_name` honours a `defer` entry BEFORE the core check, so core names defer when named. `clarify` stays (the 18/18 → 7/18 A/B in the module docstring); `patch`/`write_file` stay on dev-persona profiles and may defer on neko (the operator's call, ruling R1).
- **Then the knob (fork code, one commit):** the profile config is shared by every persona bound to it, so the durable form is per PERSONA like `chat_lane_restore_toolsets`: `agent_runtime/chat_lane_toolsets.py` gains `chat_lane_defer_tools(persona_id)` read from `agent_runtime.personas.<id>.chat_lane_defer_tools`. The door is fork-only: the chat agent is built by `agent_runtime/profile_runner/runner.py` (`AIAgent(**kwargs)`) from the toolsets `agent_runtime/chat_lane_bundle.py` resolved (`enabled_toolsets=enabled`), and upstream's constructor assembles `tools[]` through `model_tools.get_tool_definitions` → `assemble_tool_defs(config=load_config())`. Right after construction, on the chat lane only, the fork re-runs the assembly on the raw list: `raw = get_tool_definitions(enabled, quiet_mode=True, skip_tool_search_assembly=True)`; `agent.tools = assemble_tool_defs(raw, context_length=…, config=replace(load_config_readonly(), defer_tools=curated | persona_defer)).tool_defs` — `assemble_tool_defs` is idempotent by contract ("existing bridge tools are stripped first") and `config=` is already its parameter. Deferring is never a grant, so un-exclusion semantics do not apply.
- **Positive control:** `tests/agent_runtime/test_chat_lane_toolsets.py` — assemble the neko fixture list with the knob set: 31 → 18 entries, `deferred_count` 51 → 64, listing form still `full`; plant = ignore the knob → red. Live: the log line reads `tool_search activated (tier 1): 15 core/visible tools kept, 64 deferred`.
- **Saving (Neko):** ≈5,900 tokens off `tools[]` (−27 % of the request), minus ≈190 for the 13 added listing lines. Dev persona (keeps `patch`, `write_file`, `execute_code`): ≈4,700.
- **Risk:** a deferred tool costs one `tool_describe` round trip the first time a chat needs it (≈2.5 s on these models). On record that is never for these sixteen; `delegate_task`/`memory` reach the model through the listing as they do for `process_manage` (3 bridge reaches on record).

### S2 — the promoted MCP tools carry a brief, not the server's manual

- **Goal:** the four `launcher_qa` promotions keep their one-round-trip property at a fraction of 5,261 tokens.
- **Touches:** `tools/tool_search_downstream.py` (fork): the promotion applies `promoted_brief(td)` — description clipped to its first sentence or 300 chars (the `_clip_description` precedent at 500), `parameters` kept whole with each property `description` clipped to 120 chars; the FULL definition is parked in a module table `PROMOTED_FULL_SCHEMAS[name]`. `tools/tool_full_descriptions.py` (fork) answers `full_tool_description(name)` from that table so upstream's `dispatch_tool_describe` — which reads `fn.get("description")` from `current_tool_defs`, i.e. the clipped one — still serves the manual on describe (`full_tool_description(name) or fn.get("description")`, already the order upstream calls). The full `parameters` on describe come from the same table through the fork's `attach_hit_parameters` path (one additive hook; upstream's `dispatch_tool_describe` body untouched).
- **Second lever, same commit:** drop `capture_screenshot` from `_MCP_NEVER_DEFER_VERBS` (0 calls on record; `screenshot_window` is the verb the skill teaches) — 640 tokens. R2 decides.
- **Launcher half (row for `mission-control-queue.md`):** `open_app_tab`'s description is 2,087 tokens at the SOURCE (`EterniaLauncher/tool/stagec_qa_mcp_server`); the server can ship a brief `description` and move the manual into a `_meta`/`x-doc` field the fork's describe reads. Hermes trims first; the server-side trim retires the hermes table.
- **Positive control:** `tests/tools/test_tool_search_downstream.py` — the assembled `open_app_tab` schema ≤ 600 chars of description while `dispatch_tool_describe(["mcp__launcher_qa__mcp_launcher_qa_open_app_tab"])` returns the full text; plant = return the clipped text from describe → red.
- **Saving:** 5,261 → ≈1,900 (−3,300) with four promoted; → ≈1,400 with three.

### S3 — the skills index lists the persona's skills, names the rest

- **Goal:** the 96-entry index becomes nine full entries plus names-only lines for every other category — nothing hidden (upstream's own rule: agent-created skills are project memory).
- **Why it is 96 today:** upstream's `agent/system_prompt.py::_skills_prompt` computes `compact_categories` from `agent.coding_context.coding_compact_skill_categories(platform=agent.platform, cwd)`; `_detect_profile` returns the GENERAL profile for any platform outside `INTERACTIVE_CODING_PLATFORMS = {cli, tui, acp, desktop, ""}`, and the mission chat runs as `platform=tool` (the log's `conversation turn … platform=tool`), so nothing is ever demoted on this lane. Even under `focus` the demotion is a fixed non-coding deny-list, not a per-persona one.
- **Touches:** the set is computed on the fork side — "every category that holds none of `mission_chat_operating_skills(persona)` ∪ the persona's declared `skills`" (`agent_runtime/chat_lane_scope.py::mission_chat_operating_skills` is the existing resolver; the fork's record builder already does the twin computation at `model_input_observability.py:433`) — and handed to the chat agent as an attribute before the prompt builds (`agent._chat_lane_compact_skill_categories`, set in `agent_runtime/profile_runner/runner.py` beside the constructor). Reaching the index needs ONE additive line in upstream `agent/system_prompt.py::_skills_prompt`: `_compact_cats = frozenset(_compact_cats) | frozenset(getattr(agent, "_chat_lane_compact_skill_categories", ()) or ())` — a seam row in `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md` (held PR: "compact_categories override attribute"). Rejected: pointing `skills_dir_override` at a persona-scoped view of nine skills — that hides the other 87 from `skill_view` too, which upstream's "never drop entries" rule forbids.
- **Positive control:** `tests/agent_runtime/test_persona_prompts.py` — the rendered index for a persona declaring two skills in one category shows that category in full and every other as `[names only]`; plant = pass `None` → red.
- **Saving:** Neko 1,853 → ≈700 (−1,150); Dev 3,711 → ≈1,100 (−2,600). The `.skills_prompt_snapshot.json` cache key already includes `compact_categories` (`prompt_builder.py:1482`), so the snapshot stays valid per persona.

### S4 — the operative rules stop restating the foundation

- **Goal:** `_mission_chat_operative_rules` (2,088 tokens) keeps every rule that is Mission-Control-specific and drops what the upstream stable prompt already says two screens above it.
- **Touches:** `agent_runtime/mission_chat_prompts.py` (fork). Candidates, by overlap with the recorded foundation: "act on a clear instruction in the same turn / never end asking permission" (≈480 tokens) overlaps `<act_dont_ask>` + `<mandatory_tool_use>` (284 upstream tokens); "never fabricate" (≈70) overlaps `<external_state_verification>`; the three `agent_chat_send` threading bullets (`session_id`, `clarify_token`, `@personainst_*` handles, ≈600) belong to the tool's own describe doc (`tools/agent_chat/schemas.py` description + `tool_full_descriptions`) and the `harness-mission-lead` skill, where only the persona that dispatches pays them; the charsheet-delegation bullet (≈150) is a skill-routing fact for one persona. Target ≤ 1,000 tokens.
- **Positive control:** `tests/agent_runtime/test_persona_prompts.py` gains a chars ceiling on the rules (4,000 chars) with the killing mutation "paste one retired bullet back" → red; a behaviour check is NOT a unit test — see R4.
- **Saving:** ≈1,100 tokens, on every persona.

### S5 — the deferred listing stays full (decision, no change)

- The listing is 981 tokens of the 4,000 budget (1,261 for Dev). Names-only would save ≈500 and cost a `tool_search` round trip on the 9-of-64 turns that reached a deferred tool by name through `tool_describe` directly (21 describes vs 9 searches on record: the agent reads the listing and skips search, which is what the listing is for). Keep `listing: auto`, `listing_max_tokens: 4000`. R3 records it.

### S6 — the first turn hits the persona's cached prefix

- **Goal:** a new chat's turn 1 reuses the bucket the persona's previous chat filled, since its `instructions + tools` bytes are identical.
- **How it is routed today:** the fork's `agent_runtime/cache_routing.py::apply_persona_cache_routing` (an `llm_request` middleware over upstream's Responses kwargs) sets the body `prompt_cache_key` to the content hash of `instructions + tools` — "the scope never enters it" — and puts the bounded `cache_scope_id` into the Codex `session_id` and `x-client-request-id` headers. The scope is the CHAT: `agent_runtime/persona_runtime.py:249 cache_scope_id=perm_session_id` and `agent_runtime/persona_chat_actor_prewarm.py:590 cache_scope_id=root`. So two chats of one persona send the same body key under two session headers, and the record's `session_header_fingerprint == client_request_header_fingerprint` is that header. That the provider routes its cache by the header and not by the body key is the inference from "same bytes, no `cache=` on a new chat's turn 1" — UNVERIFIED as a provider fact; S6's live control is the read.
- **Touches:** the two setters above pass `persona_chat:<persona_instance_id>` (the chat's `persona_instance_id` is on the record and on `AgentPersona`) instead of the session id; `cache_routing.py` unchanged. The content hash already changes the key whenever SOUL/skills/tools change; the scope only decides which conversations may share a bucket. Issue #78941's concern ("unrelated sessions in one bucket") is answered by scoping to one persona instance on one profile, never wider.
- **Positive control:** `tests/agent_runtime/test_persona_runtime_fake.py` — two chat roots of one instance produce one `prompt_cache_key_fingerprint` in their records; plant = scope by session id → red. Live proof: the second chat's `API call #1` line carries `cache=`.
- **Saving:** the whole ≈21k prefill on 37 % of turns — UNVERIFIED in seconds (the §0.4 read). Both Codex headers carry the scope from the one setter, so the header and the scope move together.

---

## 2. Savings, summed (Neko first turn, tokens)

| stage | before | after | saving | cumulative request |
|---|---|---|---|---|
| S1 defer the never-called 16 (13 named) | tools 16,580 | ≈10,700 | −5,900 | ≈16,100 |
| S2 brief the promoted MCP four | 5,261 of those | ≈1,900 | −3,300 | ≈12,800 |
| S3 persona-scoped skills index | 1,853 | ≈700 | −1,150 | ≈11,650 |
| S4 rules dedupe | 2,088 | ≈1,000 | −1,100 | ≈10,550 |
| S6 persona-scoped cache | 21,957 uncached on turn 1 | ≈0 uncached | prefill on 37 % of turns | — |

≈22k → ≈10.5k on every chat's first turn (−52 %); the Dev Agent ≈36k → ≈22k (its SOUL and memory are operator content and stay). The cached later turns gain nothing in tokens billed (they already hit) and ≈0 in latency; the gain is the first turn and every cache miss.

---

## 3. Open rulings (recommendation first)

- **R1 — what stays eager per persona.** Recommend: supervisor (neko) eager = `terminal`, `read_file`, `search_files`, `skill_view`, `skills_list`, `clarify`, `agent_chat_send`, `agent_chat_dispatches`, `skill_search`, bridge trio, promoted `launcher_qa` three (S2) — 15 tools. Dev/backend personas add `patch`, `write_file`, `execute_code`, `web_search`, `web_extract`. The worker lane (`persona_runtime.run_persona`) is untouched. Alternative rejected: one global list — the profile config is shared by every persona bound to it, so the per-persona knob (S1 second half) is the durable form.
- **R2 — the `launcher_qa` promotion set.** Recommend three (`open_app_tab`, `screenshot_window`, `launch_or_attach`); `capture_screenshot` rides the listing. In the qa and neko profiles' skills, `capture_screenshot` is named only by `mcp/native-mcp/SKILL.md` (the generic MCP manual), not by `launcher-stagec-mcp-screenshot`, and it has 0 calls on record.
- **R3 — the deferred listing.** Recommend keep full (S5). The budget could fall from 4,000 to 2,000 with no effect today (981/1,261 used) and would cap a future server; leave it.
- **R4 — the rules cut needs a behaviour proof, not a char count.** Recommend: land S4 behind the same A/B the clarify ruling used — ten live supervisor turns that include one "send X to QA" and one "screenshot news" with the trimmed rules, compared on `tool_turns` and on whether the first tool call was preceded by a sentence (the HARD RULE). The owner runs them; the lane records them in the commit body.
- **R5 — cache scope per persona instance, per persona, or per profile.** Recommend per persona INSTANCE (`personainst_*`): two instances of one persona may differ by SOUL overlay and memory, and the hash would split them anyway. Wider than that is #78941's concern.
- **R6 — prefix order.** The current order (tools, then instructions; HUD and skill preload on the user turn) is already the cache-friendly one and matches the T5/T9a invariant; no change. Recorded, so the next lane does not reopen it.

## 4. UNVERIFIED, each with the one read that settles it

- The split of the uncached first call's 1.7 s between prefill and the first connection (§0.4): a turn-1 ledger with `builds_overlapped = 0` and a pooled connection.
- That the Codex cache routes by the `session_id` header rather than the body `prompt_cache_key` (S6): the second chat's `API call #1` line after S6 lands.
- Tokens per tool are tiktoken-on-JSON; the provider's own count is ≈0.9× for tools and ≈1.0× for text (21,957 metered vs 24.7k summed). Every saving above is quoted in tiktoken tokens; the metered saving is ≈10 % smaller on the tool rows. S0's chars receipt settles each stage against the metered `in=`.
- The 51/69 "deferred" counts in the log include plugin and check_fn-gated tools the offline rebuild could not register (it reproduced 34/48); the per-tool numbers in §0.2 are exact for the 31 visible entries and the listing is reproduced at 981/1,261 tokens against the log's 4,000 budget.

## 5. Findings filed from this lane (rows for `runtime-queue.md` § Fork-owned; the report carries them verbatim)

- **`model_tool_tokens` is not a measurement:** `agent_runtime/tool_visibility.py::_estimate_model_tool_tokens` returns `sum(max(8, (len(name) + 96) // 4))` over tool NAMES, so doc 05 §4c's "43 callable tools, `model_tool_tokens` 1149" describes a 12-token-per-tool fiction while the request carries ≈16.6k; S0's receipt replaces it and the doc line is re-measured then.
- **The profile configs carry a dead `agent.tool_search:` block** (`neko`, `gpt-launcher`): the loader reads `tools.tool_search`; nothing reads the `agent.`-prefixed one. Delete with S1's config edit.
- **The chat lane's cost policy is bypassed under `unbounded`** (doc 05 §4), so `chat_lane_toolsets.py`'s whole reason to exist — "a supervision chat does not drive a browser, analyze images, or execute code" — is inert on the default posture; S1's per-persona defer knob is the posture-independent form of the same policy.
