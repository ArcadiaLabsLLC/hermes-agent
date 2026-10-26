# The boot's cold first build: what is cold, and what the prewarm can take off the first open (plan)

Status: PLAN — written and ruled 2026-10-26 by lane w1025b-h-stream ("go with recommendations",
the wave brief's rule for NEEDS PLAN rows). Row: runtime-queue `RT-PREWARM-BUILD-AGENTS-READINESS-COLD`.
S0 measured offline, S1 BUILT; S2 waits on the wave's idle-box perf phase.

## In plain English

Every time the serve starts, its first snapshot build takes 5–13 s instead of about 1 s, and most of
that is one section, `agents_readiness`. The reason is not the data: it is Python importing every tool
and plugin module for the first time in that process. The serve also pays the same imports again in
its own process for the first chat turn, and until now it waited for the build to finish before
starting on them, so a message sent in the first seconds after boot paid them itself.

## Evidence

- Live, eight boots 2026-10-20..25: the first (prewarm) build 5.0–13.3 s, `agents_readiness`
  2.9–7.8 s of it (walk 1.8–5.3 s, tool_visibility 1.0–3.0 s); later builds 0.8–1.5 s
  (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md` § RT-SNAPSHOT-BUILD-SLOW-AFTER-RESEED).
- Live 2026-10-25 22:38: turn P1 sent 4 s after `ready` read send-prep 7,723 ms (`cpu_ms` 7,390,
  `context_built_ms` 2,261) while the worker's prewarm build ran 6,261 ms (same note, § Timing batch).
- **S0, offline (this plan, 2026-10-26)** — a cold child process over the seeded store of
  `tests/agent_runtime/test_stream_relay.py::seeded_store` (4 personas, 60 skills, frontmatter cache
  primed), `cProfile` around `build_snapshot`, box under load (absolute times inflated, shares hold):
  - build 8.4 s, `agents_readiness` 6.7 s; of it `tool_visibility.resolve_tool_visibility` 6.3 s.
  - 785 modules imported inside the build; `_io.open_code` (reading `.pyc`) 2.55 s self time.
  - `_ensure_plugin_tools_registered` → `discover_plugins` 3.25 s (32 plugins loaded, e.g.
    `plugins/dashboard_auth/basic` 1.19 s, most of it importing `httpx`).
  - `_ensure_tool_registry_populated` → `model_tools` import → `discover_builtin_tools` 1.9 s.
  - `_estimate_model_tool_tokens` 2.3 s (cumulative, overlapping the two above).
  So what is cold is **module import**, per process — not the per-persona profile reads, which are
  milliseconds.

## Decisions (recommendation first; ruled "go with recommendations")

1. **Where the serve's own warm runs.** Recommend: beside the worker-bound build, not behind it. The
   build runs in the snapshot worker's interpreter, so the serve's import warm cannot contend for its
   GIL; the sequential order exists for the in-process case and stays there. **Ruled: yes (S1).**
2. **Whether the worker can skip the imports.** Recommend: measure first (S2). The worker pays the
   imports on its first build by construction; spawning it earlier (at socket bind, before `ready`)
   and pre-importing `model_tools` + plugin discovery there would overlap them with the serve's own
   boot (`dispatch` 1.6–3.1 s live), but only an idle-box boot timing says whether the overlap is
   real. **Ruled: S2 is a perf-phase measurement before any build.**
3. **A persisted tool catalog** (tool names per toolset keyed by the code tree, so a cold process
   reads names without importing plugins — the CF-2 frontmatter cache's shape). Recommend: not now;
   it is a new derived cache with an invalidation story, and S1 + S2 may make it unnecessary. **Ruled:
   deferred until S2's number.**

## Slices

- **S0 — attribute (DONE offline, above).**
- **S1 — the serve's provider warm beside a worker-bound build (BUILT).**
  `hermes_cli/harness_parts/serve/boot.py::_prewarm_read_model_snapshot_in_worker` starts
  `_provider_warm_steps` on its own thread once `bind()` answers True; the sequential
  `_prewarm_provider_runtime` step joins it, so the actor prewarm still starts after it. In process,
  unchanged. Test: `tests/hermes_cli/test_serve_concurrent_provider_warm.py`; red recorded: drop the
  start call → `assert False is True` (the warm did not run during the build).
- **S2 — perf phase, idle box.** Two boots of the owner serve: (a) the send-prep of a turn sent
  ~4 s after `ready` (target: under 1 s, against 7,723 ms); (b) the worker's first-build
  `agents_readiness` with the worker spawned at bind time and `model_tools` + plugin discovery
  pre-imported there (prototype off main). Decide decision 3 from (b).

## Blast radius

S1: one fork module (`boot.py`), boot-time threading only; the in-process path is byte-identical.
S2: the snapshot worker's spawn point (`agent_runtime/snapshot_worker/`), fork-owned.
