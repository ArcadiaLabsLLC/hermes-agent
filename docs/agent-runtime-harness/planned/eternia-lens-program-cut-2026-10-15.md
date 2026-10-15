# Eternia Lens — the program cut into lanes (design)

Status: PLAN — written 2026-10-15; owner approval owed for the CUT (the design
itself is owner-approved: all four §6 rulings accepted 2026-10-02). Row:
runtime-queue, "Build Eternia Lens as a fork-owned plugin …". Source of truth
for WHAT is built: [eternia-lens-in-hermes.md](eternia-lens-in-hermes.md)
(§3 contract, §4 cuts, §5 stages). This note only says HOW it is cut into
landings and what changed in the tree since 2026-10-02.

## In plain English

Lens watches the user's own systems (HTTP endpoints, Prometheus, databases),
and when a rule trips — "CPU over 90 for five minutes" — it opens an Episode
and starts one chat turn of the chosen agent with the evidence attached. The
design is approved; it was never started because it was dropped into row
batches where it does not fit. This cut makes it five program lanes, one stage
each, with the launcher's read-only panel paired to the stage that feeds it.

## Re-verified against `origin/main` 428e2b0dd09

- Still absent: `agent_runtime/lens/`, `plugins/eternia-lens/` — greenfield.
- Fork plugin precedent exists: `plugins/eternia-harness/`.
- Exit door still exists: `agent_runtime/mission_chat_door.py::run_mission_chat_turn`
  (l.95).
- RPC seam home exists (fork-owned): `agent_runtime/serve_rpc/` (one module
  per surface, `registry.method`).
- Push door seam: `hermes_cli/plugins.py::register_platform` (l.785).
- New since the plan: source credentials are settled as **hermes credential
  pool, write-only from the Launcher, scoped per persona home** — proposed in
  `EterniaLauncher/docs/companion/planned/MONITORING_CREDENTIALS_SEPARATION_2026-10-15.md`
  (owner approval owed there too); L1 below depends on that ruling.

## The cut

| Lane | Stage | Lands (from plan §5) | Its red-first gate | Size |
| --- | --- | --- | --- | --- |
| lens-L0 | skeleton + contracts | plugin yaml; `wire_value`, `manifest`, `seal`, `feed`, `rules`, `episode`, `evidence`; conformance corpus ported from `Eternia-Companion/packages/eternia_monitor_contracts/test/conformance/`; `runtime.lens.list` | unknown manifest key accepted → red; 4-minute breach fires a 5-minute rule → red | 7 modules + corpus |
| lens-L1 | poll door | `sources/http_json`, `sources/prometheus`, `store`, `retention`, `poller` under serve; the ten `runtime.lens.*` verbs; snapshot fold; credential refs | three failed polls record no gap → red; >24 h raw rows survive retention → red; a resolved credential value appears in stored evidence → red | 5 modules + RPC |
| launcher-lens-L1 | fold painter | Mission Control reads the fold: open Episodes, latest value per feed, last receipt — read only (the existing mission-control-queue L1 row) | an Episode in the fold is not painted → red | launcher |
| lens-L2 | exit door | `trigger`, `artifacts`, `tool` opening block; daily cap, pause, receipts | one Episode forges two turns → red; capped monitor forges → red; `report.md` written but no artifact handle → red | 3 modules |
| lens-L3 | push door | `ingress` via `register_platform`; HMAC + Svix; Alertmanager + Grafana mappings | wrong signature creates an observation → red; `resolved` body opens an Episode → red | 1 module + mappings |
| lens-L4 | pull door | `lens_read` tool; `sql_readonly`, `command` sources; `via: kube_proxy` | undeclared profile reaches `lens_read` → red; off-allow-list command runs → red | 3 modules |

Rules every lane inherits (from the plan): no upstream file edited; no file over
800 lines; nothing new in `pyproject.toml` for L0–L3; RPC first, argv only where
free (CLI contract fixture re-dumped if an argv mirror lands).

## Owner decisions (recommendation first)

1. **Approve the cut** as five hermes lanes plus one paired launcher lane, run
   sequentially (each depends on the last). Recommend yes.
2. **Credentials ruling before L1** (see the launcher plan above). Recommend
   approving it in the same sitting; L0 does not need it.
3. **Where Lens runs on a machine with no Launcher open.** The plan's W8
   recommends an honest "watcher offline since …" state with catch-up gaps.
   Recommend confirming W8(a) now, because L1's poller lifetime follows it.
4. **Start date.** Recommend L0 as the next free hermes program slot after the
   current wave; it touches no file another lane holds.

## Done criteria per lane

Each lane's recorded red(s) in its landing commit, `tests/agent_runtime/lens/`
green, the fork gates green, and a field note under
`docs/agent-runtime-harness/planned/` naming what it measured. L1 and L2 each
need one live proof (a real HTTP feed polled by serve; a forged turn visible in
the Console).

## Blast radius

New package and plugin only, plus one import in `serve_rpc/`, one bundle yaml
line, and the launcher fold consumer at L1. Nothing deleted.

## What it retires

The row's "too big for a batch" loop (released twice, 2026-10-10 and
2026-10-15) — after this the row is replaced by five lane rows.
