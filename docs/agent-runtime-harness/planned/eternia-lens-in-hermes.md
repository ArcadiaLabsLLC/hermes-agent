# Eternia Lens in hermes — an ingest-and-trigger module for the Mission Control persona

**Status: proposed, written 2026-10-01. Not approved. Nothing here is built.** Program cursor: `Harness_Brain/20 — Active Initiatives/runtime-queue.md` (the row under "Owner asks — 2026-10-01"). The launcher half is one row in `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`, filed the same day.

## 0. The ask, and the one sentence that scopes it

Owner, 2026-10-01: integrate Companion's Lens as its own module serving the Mission Control persona on **both** Eternia Harness distributions — the packaged wheel the Launcher ships (bundled profile) and the Developer Edition (the repo checkout) — and chop every part that does not serve one purpose: *a service that receives specialised and arbitrary external information, parses it to trigger agent runs so the agents generate artifacts from the data, and lets the user pull their own data from their own systems on demand.*

So the module has exactly three doors and one exit:

| door | meaning | example |
|---|---|---|
| **poll** | the module reads a source on a cadence | Prometheus query against a Rancher cluster, a health JSON endpoint, a read-only SQL count |
| **push** | a source posts to the module | Alertmanager / Grafana alert webhook, an arbitrary signed JSON POST |
| **pull** | a person or a persona asks for data now | "show me the last hour of `up{job="api"}`", a tool call inside a chat turn |
| **exit** | a rule over observations raises an Episode, and the Episode becomes **one chat turn** of the selected persona, whose output is the artifact | "CPU over 90 % for 5 min" → the persona investigates and writes a report |

Everything in Companion's Lens that is not one of those four is cut (§4).

## 1. What is true today (measured 2026-10-01)

**In Companion** (`S:/ArcadiaLabs/Eternia/EterniaCompanion`): Lens is three things with one name. `packages/monitoring/` (about 9.7k lines, pure Dart, no Flutter, no Work import — contracts, protocol codecs, a headless poll runtime) is the part the ask describes. `packages/lens/` (spec, protocol, widgets, generative UI — 10k lines, half of it Flutter) is presentation. `lib/src/lens/` (76 files, 17.5k lines) is the Companion app's authoring UI, investigation, repair, runbooks and GenUI, every file of it bound to the Companion Work engine. The daemon's monitoring side (`packages/eternia_daemon/lib/src/monitor_*.dart`, 35 files, 10.1k lines) has pure source code (HTTP, Prometheus through `kubectl proxy`, Postgres, SQLite, allow-listed commands, win32 local metrics, the SQLite store with retention) and a 1.4k-line Work adapter. Monitoring is **poll-only**: no webhook or alert receiver exists anywhere in the daemon. Its own ADR says the part that matters here out loud: *"Mission Control requires its own Hermes integration. A Companion harness route is not proof of that integration"* (`docs/decisions/0207-monitoring-local-manifest-custody.md`).

**In hermes** (this repo): there is one Python package. The "wheel" is a **bundle profile** (`agent_runtime/bundle_profiles/bundled-desktop.yaml`, `bundled-phone.yaml`; a plugin ships only if listed under its `plugins:`), the Developer Edition is the checkout (`updates.checkout_bound`, `agent_runtime/build_stamp.py`). "Enable, never reimplement" is the owner's rule for the two (`EterniaLauncher/docs/embedded_hermes/planned/README.md`): one codebase, profiles are switches. The Eternia Harness itself is a plugin, `plugins/eternia-harness/plugin.yaml`, with its code under `agent_runtime/`. The launcher talks to `harness serve` over the push lane (snapshots, `agent_runtime/stream/`) and the method lane (JSON-RPC, `agent_runtime/serve_rpc/`); writes are RPC-first (ADR 0003). **There is no "Mission Control persona"**: it is whichever persona Mission Control has selected (`agent_runtime/mission_chat_persona.py::resolve_mission_chat_persona_id`).

hermes already has pieces of each door, none of them a rule engine:

- upstream `cron/monitor.py` — a cron job can poll a URL or script, hash the output, and run the agent only when the hash changes. Upstream-owned; diff semantics only; one minute tick.
- upstream `gateway/platforms/webhook.py` — HMAC-validated POST routes rendering a prompt template. Upstream-owned.
- `hermes_cli/plugins.py::register_platform` — a plugin can register its own platform adapter, so a push door needs **no edit to upstream's webhook file**.
- `agent_runtime/mission_chat_door.py::run_mission_chat_turn` — the one in-process door to a mission-chat turn; `agent_runtime/dispatch_delivery/forge.py` already forges a turn from a non-human event (a finished dispatch). The exit door is this, reused.
- Prometheus, Alertmanager, an alert-rule engine, Lens, Episodes: not found in hermes. No artifact store exists; cron writes `~/.hermes/cron/output/<job>/<ts>.md`, chat media is served by content handle (`agent_runtime/media_handles.py`, `runtime.media.get`).

**The consequence that decides the shape:** the Companion code is Dart and the target is a Python wheel. The Dart packages cannot be "integrated"; the module is a **port of Monitoring's contracts and runtime into Python**, inside hermes, and the Dart stays where it is as the reference (its conformance corpus, `packages/monitoring/eternia_monitor_contracts/test/conformance/`, becomes the port's test oracle). This is also the only shape that satisfies "both distributions" without a second implementation.

## 2. The decisions this plan takes (owner can overrule any one)

1. **It is a hermes plugin, fork-owned, in its own directory: `plugins/eternia-lens/`** with its Python package under `agent_runtime/lens/` (the Fork Boundary Map's fence: new modules under fork-owned dirs; the harness plugin uses the same split). It ships in the bundle by one line under `plugins:` in `bundled-desktop.yaml`; the Developer Edition has it by checkout. `bundled-phone.yaml` does **not** list it — a phone does not poll Prometheus; it reads Episodes through the paired desktop's serve session like everything else.
2. **The exit is a chat turn, never a new lane.** ADR 0008 ("Chat is the only lane") refuses any new orchestration lane unless it rides a chat turn. An Episode is forged into the selected persona's chat root through `run_mission_chat_turn`, exactly as a dispatch delivery is forged today. The turn carries a bounded evidence envelope; the persona's reply and any files it writes are the artifact.
3. **No cron, no Work.** The upstream cron monitor is not the poller (upstream-owned, hash-diff semantics, cannot express "over threshold for 5 minutes"). The native Work service (`runtime.work.*`) is not the exit (ADR 0008 again, and the Companion Work adapter is the single largest thing being cut). The module runs its own asyncio poller **inside the `harness serve` process** under the existing serve lifecycle; it is a reader with a clock, not a scheduler of agents.
4. **Lens the name, Monitoring the content.** The owner calls the product Lens; the plugin is `eternia-lens`. What it contains is Companion's *Monitoring* bounded context (manifests, feeds, rules, Episodes, evidence, retention). The Lens presentation packages are not ported (§4) — Mission Control is the presentation.
5. **Presentation in the launcher is a read of hermes, nothing more.** Episodes, current values and artifact handles are folded into the snapshot the push lane already carries, and queried over the method lane. No Dart monitoring runtime, no second store, no chart kit in this plan. Charts are a later owner decision, if ever.
6. **The `act` automation level is cut from this plan.** Companion's three levels are notify / investigate / act. This plan ships notify and investigate. "Handle it" (the agent applies a fix inside pre-approved permissions) needs the per-monitor reviewed-approval machinery Companion built on its Work engine; in hermes it would ride the persona's ordinary tool permissions in the same chat turn, and that is a separate decision with its own gate — not a chop, a deferral, filed as such.

## 3. The contract (what is ported, in Python, under `agent_runtime/lens/`)

Every file under the 800-line ceiling (ADR 0007). Names follow the Companion contracts so the conformance corpus maps one-to-one.

| module | ported from (Companion) | owns |
|---|---|---|
| `wire_value.py` | `monitor_contracts/src/wire_value.dart` | strict bounded canonical JSON: unknown key, duplicate key, non-finite, oversize all refuse |
| `manifest.py`, `seal.py` | `monitor_manifest.dart`, `monitor_seal.dart` (simplified) | the Monitor definition: feeds, rule, automation policy `{level: notify\|investigate, when: urgent\|always, daily_turn_cap}`, target persona; sealed = immutable bytes + sha256 + revision. Host/generation/lease fencing is dropped (one process owns the store) |
| `feed.py`, `sources/http_json.py`, `sources/prometheus.py`, `sources/sql_readonly.py`, `sources/command.py` | `monitor_feed.dart`, `read_source.dart`, `http_connection.dart`, daemon `monitor_http_*`, `monitor_kubernetes_connections.dart`, `monitor_postgres_read.dart`, `monitor_command_*` | feed kinds `http_json`, `prometheus` (the HTTP API directly: `/api/v1/query` and `query_range`, bearer or basic from the hermes credential pool; the `kubectl proxy` route becomes an optional `via: kube_proxy` later), `sql_readonly` (sqlite3 stdlib first, Postgres when `psycopg` is already in the closure), `command_allowlisted`. `local_metric` (win32 FFI) is **not** ported; `psutil` is a later, separate add |
| `series.py`, `snapshot.py`, `source_alert.py` | `monitor_series.dart`, `monitor_snapshot.dart`, `source_alert.dart` | observations with source time, explicit gaps, typed alert observations (the push door's output) |
| `rules.py` | `rule_evaluator.dart`, `rule_defaults.dart`, runtime `monitor_rule_reader.dart` | threshold / for-duration / missing-data rules, severity, deterministic over the store |
| `episode.py` | `monitor_episode.dart`, runtime `monitor_incidents.dart` | open → (turn forged) → recovered / closed; one Episode per rule breach, recovery is not resolution |
| `evidence.py` | `monitor_evidence.dart`, runtime `monitor_evidence_reader.dart` | the bounded redacted window (default 32 KiB, up to 4 feeds, 7 days, optional 60 s rollups) the turn carries |
| `store.py`, `retention.py` | daemon `monitor_database*.dart` | one SQLite file under `HERMES_HOME/lens/lens.sqlite3` (WAL): manifests, observations, minute rollups, Episodes, turn receipts; 24 h raw + 7 d rollups, never silently shortened |
| `poller.py` | runtime `monitor_runtime.dart`, `monitor_poll_scheduler.dart` | the asyncio loop under serve; per-feed cadence, backoff, gap recording |
| `ingress.py` | **new** (Companion has none) | the push door: a plugin-registered platform adapter; HMAC-SHA256 or Svix signature; a declared mapping `{json_path → feed, alert fields → source alert}`; Alertmanager v4 and Grafana unified-alerting bodies as the two shipped mappings, arbitrary JSON through the generic mapping |
| `trigger.py` | daemon `monitor_work_adapter.dart` (the 1.4k-line thing, reduced to ~150) | Episode → forged turn through `run_mission_chat_turn` on the manifest's persona (default: the selected Mission Control persona); idempotent per Episode; `daily_turn_cap` and a per-monitor pause checked at admission; the receipt row `{episode_id, turn_id, started, outcome, artifact_handles}` |
| `artifacts.py` | **new** | the turn's working folder `HERMES_HOME/lens/episodes/<episode_id>/`; files the persona writes there are registered as media handles after the turn; the receipt names them |
| `rpc.py` | `monitor_protocol` (the `MonitorMethod` enum) | `runtime.lens.*` on the method lane, `TIER_CONSOLE`: `create`, `seal`, `enable`, `pause`, `retire`, `list`, `get`, `preview` (one-shot read of a draft feed, no store write), `latest`, `range`, `episodes`, `receipt`, `ingress.register`. Registered through a one-import seam in `agent_runtime/serve_rpc/` (fork-owned) |
| `tool.py` | `monitor_investigation_brief.dart` (the prompt) | the persona-side tool `lens_read` (`monitor`, `feed`, `range`) so the pull door works inside a turn; admitted per profile declaration like any tool (ADR 0009); plus the forged turn's opening block |
| `snapshot_fold.py` | — | the push-lane fold: open Episodes, latest value per enabled feed, last receipt — the launcher paints this, nothing else |

Three facts the port keeps from Companion verbatim, because they are the honesty the product rests on: a gap is a gap (never interpolated); a missing capability is reported `unavailable`, never faked; applied is not verified and recovered is not resolved.

## 4. What is cut, and why each cut is safe

| cut | lines | why it does not serve the four doors |
|---|---|---|
| `packages/lens/*` (spec, protocol, widgets, generative_ui) | ~10k | presentation and GenUI; Mission Control is the presentation, and a Dart chart kit cannot live in a Python wheel |
| `lib/src/lens/*` repair, runbooks, action approval, recovery settings, workflow author | ~3.5k | the `act` level on the Companion Work engine; deferred (§2.6), not ported |
| `lib/src/lens/*` investigation UI, settings, evidence access, insight dialogs | ~3k | all bound to `eternia_work_client`; the one thing they carry (the investigation request shape) is kept as `evidence.py` + `trigger.py` |
| `lib/src/lens/*` views, cards, editors, composer, windows, notifications | ~11k | Companion app UI; the launcher half is one fold and one method consumer |
| daemon `monitor_work_adapter.dart` + parts, `monitor_decision_executor.dart` | ~2.6k | the Work binding; replaced by the ~150-line forge in `trigger.py` |
| daemon `monitoring_daemon.dart`, `local_service_rpc_server.dart`, the daemon descriptor/operator token | ~0.6k | a second process and a second socket; hermes serve is the process and the socket |
| daemon `monitor_local_metrics.dart` (win32), `monitor_command_process.dart` (win32), `secure_vault_windows_ffi` reads | ~0.7k | platform FFI and a Companion credential namespace the launcher never admitted (`EterniaLauncher/docs/companion/planned/BLEND_DECISIONS_2026-09-23.md`, "Monitoring admission"); credentials come from the hermes credential pool |
| daemon `monitor_insights*`, runtime `monitor_insights.dart` | ~0.6k | scheduled "insight" turns are a trigger kind, not a subsystem: a manifest may carry `schedule:` and the same `trigger.py` forges the turn. Kept as one field, not as a module |
| contracts `monitor_admission.dart`, `monitor_response.dart`, `monitor_ports.dart` Response* ports | ~1.2k | the typed Work owner contract (offer / inspect / capabilities / receipts); one receipt row replaces it |
| seal fencing: host id, watcher generation, write lease, rejected-write counter | — | two-process custody; the store has one writer |

Nothing in Companion is deleted by this plan. The source stays frozen as the reference.

## 5. Sequence (each stage lands alone; each has a red-first gate)

| stage | lands | gate (the mutation that must red) |
|---|---|---|
| **L0 — skeleton and contracts** | `plugins/eternia-lens/plugin.yaml`; `agent_runtime/lens/{wire_value,manifest,seal,feed,rules,episode,evidence}.py`; the conformance corpus ported from `eternia_monitor_contracts/test/conformance/` as `tests/agent_runtime/lens/`; bundle yaml line; the serve_rpc seam with `runtime.lens.list` only | a manifest with one unknown key is accepted → red. A rule "over 90 for 5 min" fires on a 4-minute breach → red |
| **L1 — poll door** | `sources/http_json.py`, `sources/prometheus.py`, `store.py`, `retention.py`, `poller.py` under serve; `runtime.lens.{create,seal,enable,pause,retire,get,preview,latest,range,episodes}`; the snapshot fold | a feed that fails three polls records no gap → red. Raw rows older than 24 h survive a retention pass → red. **Launcher row:** paint the fold (open Episodes + latest values) in Mission Control — read only |
| **L2 — exit door** | `trigger.py`, `artifacts.py`, `tool.py` (opening block); notify and investigate levels; `daily_turn_cap`, pause; receipts; `runtime.lens.receipt`; artifacts as media handles | the same Episode forges two turns → red. A monitor at its daily cap forges a turn → red. A turn that wrote `report.md` leaves `artifact_handles` empty → red |
| **L3 — push door** | `ingress.py` as a plugin-registered platform; HMAC + Svix; Alertmanager and Grafana mappings; generic json-path mapping; `runtime.lens.ingress.register` | a POST with a wrong signature creates an observation → red. An Alertmanager `resolved` body opens an Episode → red |
| **L4 — pull door** | `lens_read` tool (profile-declared); `sources/sql_readonly.py`, `sources/command.py`; `via: kube_proxy` for Prometheus behind Rancher without an ingress | a profile that does not declare `lens_read` reaches it → red. A command outside the allow-list runs → red |
| **later, separate decisions** | the `act` level; `psutil` local metrics; charts in the launcher; Postgres when `psycopg` enters a bundle closure | — |

Rules the sequence obeys: one plugin, one package, no file over 800 lines, no edit to an upstream file (the push door is `register_platform`, the RPC seam is in fork-owned `serve_rpc/`); nothing new in `pyproject.toml` for L0–L3 (`aiohttp` and `sqlite3` are already in the closure — "bundle only what is needed"); the CLI contract fixture is re-dumped at the landing that adds `harness lens …` argv mirrors, if any (ADR 0003: RPC first, argv only where free).

## 6. What the owner is asked to rule on, before L0

1. **Name:** `eternia-lens` for the plugin and `runtime.lens.*` for the methods (the product's name), or `eternia-monitor` (the content's name). This plan assumes the former.
2. **Persona targeting:** per-manifest persona with the selected Mission Control persona as the default (assumed), or always the selected persona.
3. **The `act` level stays out** of this plan (assumed; §2.6).
4. **Phones do not run the poller** (assumed; §2.1).

## 7. Provenance

Companion inventory and the hermes seam map were taken on 2026-10-01 from the two trees named in §1; the Companion product intent is `EterniaCompanion/output/home-release-gate/docs/plans/proposed/eternia-lens.md` §1, §5, §6, §10.5 (the thesis, the happy path, the scenario catalog, the three automation levels) and `docs/decisions/0207-monitoring-local-manifest-custody.md`. The hermes rulings applied are ADRs 0001, 0003, 0007, 0008, 0009 and the Fork Boundary Map's fence; the distribution vocabulary is the owner's 2026-09-29 naming ruling in `EterniaLauncher/docs/embedded_hermes/planned/README.md`.
