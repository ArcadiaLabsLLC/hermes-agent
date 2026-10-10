# L3 outcomes — lane 1010-L3 (runtime-queue § Seams), 2026-10-10

L3.01 · RETURNED upstream PR: the adoption branch in `hermes_cli/plugins.py::get_plugin_manager` is upstream's code (byte-identical on upstream/main), no fork hunk to put a real-home key in; it fires only when a test monkeypatches `_plugin_manager`; the red it caused was fixed fork-side by `fd1e4cfde6` (draft A)
L3.02 · ALREADY-DONE the row asks for attribution; the 2026-10-08 verdict attributed it (spill config 1.0 ms warm, lazy spill rejected; the 19 ms is the eternia-harness `settle_turn_tools` → `reapply_chat_lane_defer` re-assembly, sol-runtime H4) — `docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md` § Attribution pass
L3.03 · RETURNED upstream PR: reproduced by reading; `server._sanitize_client_source` is absent from upstream/main as well (upstream's own `compute_host.py` line since #65895 calls it, `tui_gateway/server.py` has only `_resolve_session_source`); the fix replaces an upstream line, not additive (draft B)
L3.04 · FIXED 9c0034a95b
L3.05 · RETURNED upstream PR: measured — `pm/environments.py::owning_home_root` only looks for the owning store under the checkout's parent (`<eternia root>`) and the platform default (`%LOCALAPPDATA%/hermes`); this box's owner is `<eternia root>/.hermes` (state present for install key `daf521d8b1d53713`), so a sandboxed home never finds it and syncs its own venv; `pm/` carries no fork hunk there. Launcher side can keep `HERMES_DISABLE_LAZY_INSTALLS=1` for sandboxed serves meanwhile (draft C)
L3.06 · RETURNED upstream PR: every fix site is upstream (`agent/transports/codex.py`, `agent/web_search_registry.py`); 2026-10-08 verdict stands (draft D)
L3.07 · RETURNED too big: moving native conversation recovery out of ~15 upstream `tui_gateway/` files is a program (hundreds of lines, one MOVE lane per file cluster); design question: which fork module owns recovery and which one-line call sites each upstream file keeps
L3.08 · RETURNED owner decision: "Go for the four door-PR Opus build lanes on `h-doors` (`d3d91edc7f`), and OK to open the four upstream PRs?"
L3.09 · RETURNED upstream PR: none of the four door PRs is opened (waits on L3.08's owner go, then on upstream merge + release)
L3.10 · RETURNED upstream PR: native and relayed thinking reach the fork's callback with identical args (`"reasoning.available", "_thinking", text, None` from both arms of `agent/turn_response_intake.py`), so `profile_runner/progress.py` cannot tell them apart; the clean door is a marker on `_relay_thinking`'s call (draft E). Fork-only alternative (owner/launcher call): drop a Thinking row equal to the reply prefix at turn end — needs the live frame retracted too
L3.11 · RETURNED upstream PR: the `API call #N` line is upstream `agent/turn_usage.py`, no fork hunk (draft F)
L3.12 · RETURNED upstream PR: `_CodexCompletionsAdapter.create` is upstream `agent/auxiliary_client.py` (draft G)
L3.13 · RETURNED upstream PR: `agent/skill_utils._load_raw_config` is upstream-owned (draft H)
L3.14 · RETURNED too big: MEASURED — the churn is real and costly: each MCP admission register + teardown moves `registry._generation`, the `model_tools._tool_defs_cache_key` memo misses every MCP-admitting turn; rebuild 202–215 ms vs 0.1–0.5 ms warm (fixture home, 44 tools, generation +2 per probe). Callers on that path: `agent/agent_init.py` (construction), `agent/tool_executor.py` (tool_search scoped names), `agent_runtime/tool_surface.py`. The key is upstream's tuple (fork hunk can only ADD a field, not drop the generation); design question: upstream PR keying the memo on registry content (as `agent_runtime.chat_lane_bundle.registry_content_revision` already does) vs keeping admitted MCP tools registered across turns (reverses the R2 teardown ruling) (draft I)
L3.15 · RETURNED upstream PR: per-agent defer door on `tools/tool_search.py` (draft J)
L3.16 · RETURNED upstream PR: passing the spawn cwd into `tools/environments/local.py::_scrubbed_env` is a seam widening (draft K)
L3.17 · RETURNED upstream PR: `agent/prompt_builder.py::_load_agents_md` needs an already-injected-hashes door (draft L)
L3.18 · RETURNED upstream PR: `gateway/run.py::_drain_gateway_watch_events` is upstream code with no fork hunk; it still discards every type but watch/heartbeat/`async_delegation` (read on HEAD); fix = requeue unknown types (draft M)
L3.19 · RETURNED upstream PR: public scoped/keyset SessionDB page query (draft N)
L3.20 · RETURNED owner decision: "OK to open one upstream PR for a configurable compute-host hello budget (default 10 s)?" — upstream still waits a fixed 10 s
L3.21 · RETURNED upstream PR: waits on #122427 / #123393 (both OPEN 2026-10-10)
L3.22 · RETURNED upstream PR: waits on #128648 (OPEN 2026-10-10)
L3.23 · ALREADY-DONE verdict sheet `docs/agent-runtime-harness/planned/fix-triage-2026-09-26.md` landed (last `598604d1b9`), DROP reverts landed 2026-09-26; nothing left but merges of the KEEP PRs
L3.24 · RETURNED upstream PR: PAR-2..6 wait on #124190/#124191/#124193/#124194/#124195/#124210 (all OPEN 2026-10-10); PAR-1 and row 14 done
L3.25 · RETURNED upstream PR: waits on #128842 and #128648 (both OPEN 2026-10-10)
L3.26 · RETURNED owner decision: "#123976 (register_command busy_policy) is closed unmerged — re-cut the PR, or give `/queue-status` a fork-side command seam? And add P6–P9 with fallback `carry` to §Stage 3?" (#123977/#123978/#123979 OPEN 2026-10-10)
L3.27 · RETURNED owner decision: the row assumes every carry leaves by merge, but on 2026-10-10 #121223 is MERGED and #121218/#121220/#121221/#121222/#121641/#121644/#121646 are CLOSED (open: #121219/#121224/#121225/#121226/#121640/#121642/#121643/#121645/#128657/#128658) — "re-cut, or carry with a reason, the fix classes whose PRs closed?" and a re-count is owed
L3.28 · ALREADY-DONE upstream chained `llm_request` callbacks: #128643 landed via #133159 as `f67d490f`, an ancestor of HEAD; `tests/hermes_cli/test_plugins_middleware_chain.py` green (2 workers). The single composed callback in `plugins/eternia-harness/` MAY now split (optional cleanup, no defect)

## Upstream PR drafts (never posted)

**A — fix(plugins): adopt a monkeypatched `_plugin_manager` under the real home, not the active override.** `get_plugin_manager` adopts a single-slot manager set by a test under `_plugin_home_key()`; when the first call after the patch happens under a temporary home override (e.g. a session DB parent), the manager is keyed there and the real-home lookup returns a different manager. Key adoption by the default home (or adopt into every lookup until reset) so a patched manager is the one every call sees.

**B — fix(tui_gateway): compute host's minimal-session fallback calls a missing `_sanitize_client_source`.** `ComputeHost._build_server_session`'s fallback session dict calls `server._sanitize_client_source(frame.get("source"))`, which `tui_gateway/server.py` does not define (only `_resolve_session_source`), so the fallback meant to recover after a failed cwd hydration raises `AttributeError`. Use `server._resolve_session_source(frame.get("source"))`; test: force cwd hydration to raise and assert the session registers.

**C — fix(pm): find the owning store for a borrowed launch under the launcher-bound root, not only the checkout parent and platform default.** `owning_home_root` checks `<checkout parent>` and the platform default for `installs/<key>/facts.json`. A store kept anywhere else (a custom `HERMES_HOME` that installed the checkout) is never found, so every sandboxed launch syncs a full venv into its own home (~5 min). Ask the checkout's published launcher which store's `tools/` it execs first, among all roots with state, or record the owning root in the install stamp.

**D — perf(transports): memoize the active web-search provider per process/home for `_openai_prefers_native_web_search`.** `request_built` resolves every web-search provider's availability per request (credential-pool loads, auth-file reads, account lookups; 25–100 ms measured). Memoize `get_active_search_provider` keyed on the config signature and credential epoch, or expose a door the transport can consult.

**E — feat(agent): mark relayed thinking so consumers can tell it from native reasoning.** `_relay_thinking` sends the assistant's own content as `reasoning.available` with the same arguments as native reasoning; consumers that render reasoning rows show the reply twice when the model has no native reasoning. Pass a `relayed=True` kwarg (or a distinct event) from `_relay_thinking`.

**F — feat(usage): log the request's reasoning effort on the `API call #N` line.** The line names model and provider but not the effort the request carried; a per-call effort change (fallback re-resolve, mid-turn switch) is unlogged. Add `effort=<value>` from the built request kwargs.

**G — fix(auxiliary): drain the settled Responses stream before closing it in `_CodexCompletionsAdapter.create`.** Closing an undrained stream discards the pooled connection; `run_codex_stream` already drains. Drain to EOF (bounded) before close so the connection returns to the pool.

**H — perf(skills): bound a multi-entry cache in `_load_raw_config`.** The one-entry cache clears on every new key, so a process that alternates profiles re-reads config on every call. Keep a small LRU keyed by path + stat signature.

**I — perf(model_tools): key the tool-definitions memo on registry content, not the registration generation.** A register/deregister pair that leaves the registry unchanged (per-turn MCP admission) moves `registry._generation` and misses the memo (~200 ms rebuild vs <1 ms). Key on a content digest of registered entries plus the check_fn epoch.

**J — feat(tool_search): a per-agent defer door.** The bridge reads defer settings only from `load_config_readonly()`; an embedder with per-agent tool policy has to rebind that function. Accept a per-agent defer set on the agent (or a resolver hook) that `tool_search` consults first.

**K — feat(environments): pass the spawn cwd to the subprocess env scrubber.** `_scrubbed_env` / `_make_run_env` see no cwd, so an env overlay keyed on working directory cannot follow a command that runs in another directory. Thread the effective cwd through.

**L — feat(prompt_builder): skip context files whose content was already injected.** `_load_agents_md`'s `seen_content` is local to its walk; let callers pass hashes of content already in the prompt so the same AGENTS.md/CLAUDE.md is not injected twice.

**M — fix(gateway): requeue unknown completion-queue events in `_drain_gateway_watch_events`.** The drain keeps watch/heartbeat events, requeues `async_delegation` and silently drops every other type, so any other producer on `process_registry.completion_queue` loses its event in a gateway process. Requeue unknown types instead of discarding them.

**N — feat(hermes_state): a public scoped, keyset-paginated session page query.** `list_sessions_rich` exposes no metadata predicate and no keyset cursor, so callers that page a filtered history must read everything. Add `page_sessions(predicate..., after=cursor, limit=n)`.
