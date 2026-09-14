# Local llama implementation checkpoint

Updated: 2026-09-14. Owner: Codex. Feature **not delivered**.
Canonical design: [local-llama-agent-console.md](local-llama-agent-console.md).

## Resume here

- Hermes branch: `codex/local-llama-runtime`; Launcher branch:
  `codex/local-llama-console`. Locate them with `git worktree list`; preserve every
  dirty worktree. Launcher queue row is TAKEN by this implementation.
- H0 real-binary proof complete. H1 foundation written; RPC/serve binding,
  provider routing, frontend, final hardening, and Q1 remain open.
- Next: review/harden `agent_runtime/local_llama/manager.py` and `router_client.py`,
  add catalog/manager failure tests, then implement `local_llama/rpc.py` and the
  owning-serve registration/shutdown hooks. Do not expose a second manager from
  a non-owning serve or a profile-scoped runner.
- H2 must wire readiness, model resolution, whole-turn leases, context and
  generation/auxiliary routing. Freeze tested DTO fixtures before Launcher work.
- The new modules are checkpoint code, not a production-ready claim. Do not
  land the runtime feature on main until the remaining contracts and proof pass.

## H0 evidence

Ran `scripts/probe_local_llama.py` against the operator's installed b10809 CUDA
binary and existing Qwen 27B abliteration Q4_K_M GGUF. Executable SHA256:
`577b3116ecab660645e244b4452c5077b8527452c64883835ce4bba476a4e289`.
Local raw receipts/logs: `qa_artifacts/local-llama-h0-verified/` in the Hermes
worktree (not committed; contain machine paths). Re-run using the script's explicit
`--executable`, `--model`, `--output`, and `--context` options; it creates its own
unused loopback port and owned process tree.

Verified with **one slot / 8192 context**: empty router startup, unauthenticated
`/models` returns 401, load, observed readiness, text answer `READY`, structured
`echo(text="hello")` tool call, tool-result round trip, unload to observed
`unloaded`, preset refresh, reload with **4096 context**, final unload and owned
process shutdown. Probe exited 0. Template reports `supports_tools` and
`supports_tool_calls`. Both load AND unload return acceptance before completion;
the manager must poll authoritative model state. `?reload=1` supports preset
refresh while the empty router remains running.

Earlier probes exposed two incorrect assumptions and were corrected: immediate
`/props` after accepted load returns 503; immediate reload after accepted unload
returns 400 while the worker still exits. The default **four slots / 32768 each**
caused severe memory pressure and a 180-second tool-call timeout. Explicit one-slot
configuration completed the tool round trip quickly. Do not reintroduce default
slot count or conflate command acceptance with readiness.

## Foundation proof and caveats

`scripts/run_tests.sh tests/agent_runtime/test_local_llama_process.py
tests/agent_runtime/test_local_llama_config.py
tests/agent_runtime/test_local_llama_manager.py` exited 0: **21 passed**.
All three files hit the runner's 300-second parallel timeout and passed its
automatic one-worker retry (process 126.7s, manager 8.8s, config 8.5s). This is
retry-green evidence, not a clean timing result. Diagnose the process test's long
duration and use a bounded serial confirmation after changes; never hide retries.
Python compile check passed for the five foundation modules.

Tests currently cover process-tree ownership versus unrelated processes, failed
launch, strict configuration validation, root comment preservation, nonblocking
start, idempotency, revision/busy guards, lease exception cleanup, restart receipt
lookup, and credential omission from read projections. Missing proof includes
catalog malformed/split cases, failure cleanup/reconciliation, real manager/router
integration, RPC auth/dispatch, provider paths, and every Launcher/Q1 obligation.

No live Hermes config was changed. No runtime feature commit has landed on main.
The pre-existing runtime-skill preload ceiling hook failure remains separately
queued; it is unrelated to this feature. Existing Launcher personal memory files
and the spatial-voice worktree remain outside scope.
