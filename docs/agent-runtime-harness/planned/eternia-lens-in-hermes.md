# Eternia Lens in hermes — an ingest-and-trigger module for the Mission Control persona

**Status: proposed, written 2026-10-01; the §6 rulings were accepted by the owner 2026-10-02. Nothing here is built.** Program cursor: `Harness_Brain/20 — Active Initiatives/runtime-queue.md` (the row under "Owner asks — 2026-10-01"). The launcher half is one row in `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`, filed the same day.

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
5. **Presentation in the launcher is a read of hermes, nothing more.** Episodes, current values and artifact handles are folded into the snapshot the push lane already carries, and queried over the method lane. No Dart monitoring runtime, no second store, no chart kit in this plan. **Owner ruling 2026-10-04: charts are kept apart from Lens.** A chart is presentation and belongs with Generative UI as a separate component, not inside this module; Lens is the data and the trigger, and a chart is one of many things that may draw from `runtime.lens.range` (§6a).
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
| **later, separate decisions** | the `act` level; `psutil` local metrics; a streaming (WebSocket) feed kind; Postgres when `psycopg` enters a bundle closure | — |

Rules the sequence obeys: one plugin, one package, no file over 800 lines, no edit to an upstream file (the push door is `register_platform`, the RPC seam is in fork-owned `serve_rpc/`); nothing new in `pyproject.toml` for L0–L3 (`aiohttp` and `sqlite3` are already in the closure — "bundle only what is needed"); the CLI contract fixture is re-dumped at the landing that adds `harness lens …` argv mirrors, if any (ADR 0003: RPC first, argv only where free).

## 6. What the owner is asked to rule on, before L0

1. **Name:** `eternia-lens` for the plugin and `runtime.lens.*` for the methods (the product's name), or `eternia-monitor` (the content's name). This plan assumes the former.
2. **Persona targeting:** per-manifest persona with the selected Mission Control persona as the default (assumed), or always the selected persona.
3. **The `act` level stays out** of this plan (assumed; §2.6).
4. **Phones do not run the poller** (assumed; §2.1).

**Ruled 2026-10-02 (owner) — all four accepted as written; L0 may start from this plan:**

1. 2026-10-02: name is `eternia-lens` (plugin) and `runtime.lens.*` (methods).
2. 2026-10-02: persona targeting is per-manifest, defaulting to the selected Mission Control persona.
3. 2026-10-02: the `act` level stays out of this plan.
4. 2026-10-02: phones run no poller.

## 6a. Owner direction 2026-10-04 — charts are not Lens, and the watch-a-deal journey

**Charts.** Ruled apart from Lens (§2.5). The owner's leaning is that a chart is a Generative UI component, separate from Lens, because Generative UI will carry far more than charts and Lens far more than chart data. Lens owes that consumer exactly one thing: `runtime.lens.range` returning a bounded series with explicit gaps. Where the component lives and who builds it is the launcher's Generative UI decision (`EterniaLauncher/docs/companion/planned/UNIFIED_GENERATIVE_UI_2026-09-30.md`), not this plan's.

**The journey the owner described** — "find me the best deal on a product, then tell me when a better deal appears, the price changes, the bid changes, or the listing is ending" — fits the three doors, and it shows the split the module rests on: *the agent finds and sets up; Lens watches for free; the agent returns only when something changed.* A persona turn does the search (its ordinary web tools, not Lens). It then proposes one feed per listing it found. Lens polls those feeds with no model in the loop. A rule fires, and one chat turn produces the artifact (the comparison, the "bid now" note).

Stated against the §3 contract, the journey needs four things the contract did not have. They are additions to existing modules, not new modules:

| addition | where | why the journey needs it |
|---|---|---|
| `lens_propose` — a persona-side tool that drafts a Monitor (feeds + rule) and returns a preview; the draft is sealed only by the operator's confirm in Mission Control, never by the agent | `tool.py`, stage L4 beside `lens_read` | the agent that found the listings is the one that knows their URLs and selectors; without this the user re-types what the agent already knows |
| change rules: `changed`, `moved_by` (absolute or percent, either direction), `below` / `above` a target | `rules.py`, stage L0 | "the price changed", "the bid changed", "tell me under 400" are not threshold-for-duration rules |
| a cross-feed rule: `best_of` (minimum or maximum across the Monitor's feeds changed holder, or beat a recorded baseline) | `rules.py`, stage L0 | "a better deal appeared" is a comparison between listings, not a property of one |
| deadline observations: a feed whose value is an instant, and the rule `ends_within` (duration) evaluated against the runtime clock | `series.py`, `rules.py`, stage L0 | "the auction is ending" fires on time remaining, with no change in the polled value |

Two limits stated up front, because the product is honest about them: a listing with no API is read through `command_allowlisted` (a reviewed script that prints the value) and is as brittle as the page it reads; and *discovering new listings* is not polling — it is a scheduled agent turn (the manifest's `schedule:` field, §4), which costs a model run each time and is capped by `daily_turn_cap`.

## 6b. Weak points and attached burdens, with options (owner ask 2026-10-04)

Owner: "I don't want weak points — if an idea I mentioned has a weak point or a burden that needs to be attached, write it down with high-end options for solutions." This is that register. Each entry names the idea it comes from, the weak point, the burden it attaches, the options from adequate to high-end, and the one this plan recommends. **Rule for this register: an idea added to §6a or later gets its entry here in the same commit, or it is not added.** Stage says where the recommended answer lands.

**Source edge**

- **W1 — a source changes shape and the feed goes quiet or wrong** (scraping, any third-party API). *Burden:* every feed needs an owner for its breakage. *Options:* (a) a visible `source_broken` state, gaps recorded; (b) a stored sample plus a shape fingerprint per feed, so drift is detected on the first bad read instead of inferred from silence; (c) **high-end:** an extractor chain per feed — structured product data embedded in the page, then page metadata, then a selector — with the answering extractor recorded on every observation, and `source_broken` raised as its own Episode whose turn sends the agent to re-find the value and propose a repaired feed for the operator to seal. *Recommended:* (b) + (c). Stage L1 (state, fingerprint), L4 (repair turn).
- **W2 — a bad parse fires a false alert** (price read as 0, wrong currency, a "from" price). *Burden:* trust; one false "dropped 100 %" and the user mutes the product. *Options:* (a) a declared plausible range per feed; (b) confirm on a second read before a rule may fire; (c) **high-end:** typed values, never bare floats — money carries currency, a deadline is an instant, a count is an integer — plus a robust outlier guard (median and deviation over the recent window) for fast feeds. *Recommended:* all three; (c) is the contract, (a)(b) are rule preconditions. Stage L0.
- **W3 — sites rate-limit, fingerprint or forbid automated reads** (scraping, deal tracking). *Burden:* terms of service and politeness are the product's responsibility, not the user's. *Options:* (a) a floor on cadence (minutes) for page-read feeds; (b) a per-host budget shared by every monitor: token bucket, `Retry-After` honoured, conditional requests so an unchanged page costs the host almost nothing, robots rules respected; (c) **high-end:** a provider port — official marketplace APIs and paid price-data providers plug in behind the same feed contract, so the brittle page read is the fallback and never the design. *Recommended:* (b) in core, (c) as the port shape from day one with page reads as one adapter. Stage L1, adapters later.
- **W4 — pages that need a real browser** (JavaScript-rendered, bot-protected). *Burden:* a headless browser is heavy to bundle and an arms race to maintain. *Options:* (a) unsupported, stated plainly at proposal time; (b) **high-end:** the agent's own browser tool reads it inside a scheduled turn, under `daily_turn_cap`, and writes the value back as an observation through a narrow `lens_record` tool so rules still run deterministically. *Recommended:* (a) at first, (b) when a real journey needs it. Never a browser inside the Lens module.
- **W5 — "the same product" is not the same** (best deal across listings: variant, condition, shipping, tax, currency). *Burden:* a comparison that ignores these is wrong, not approximate. *Options:* (a) compare list prices and say so; (b) **high-end:** a total-cost value object (price + shipping + estimated tax, converted with a dated exchange-rate feed), variant and condition as feed labels, and `best_of` allowed only inside a declared equivalence group whose membership the agent justified at proposal time and the operator sealed. *Recommended:* (b). Stage L0 (value object, group), L4 (proposal evidence).

**Trigger and cost**

- **W6 — trigger storms and runaway spend** (any change rule on a noisy source; many monitors). *Burden:* every forged turn costs a model run. *Options:* (a) `daily_turn_cap` per monitor (in the plan); (b) hysteresis and cooldown per rule so a flapping value is one Episode; (c) **high-end:** Episode coalescing — changes inside a window are delivered as one digest turn — under a global budget across all monitors, with the over-budget remainder downgraded to notify and shown, never dropped silently. *Recommended:* (b) + (c). Stage L2.
- **W7 — deadlines need better timing than a poll gives** (auction ending). *Burden:* a five-minute poll cannot serve "ends in two minutes". *Options:* (a) fixed cadence, stated accuracy; (b) **high-end:** deadline rules evaluated on the runtime clock independent of polling, with cadence tightening automatically as the deadline approaches and a final confirming read before the turn is forged. *Recommended:* (b). Stage L0 (clock rule), L1 (adaptive cadence).
- **W8 — nothing watches while the watcher is off** (every idea; the bundled harness runs only while the Launcher does). *Burden:* an always-on host, which the desktop is not. *Options:* (a) an honest "watcher offline since …" state and catch-up on resume: missed windows become gaps, deadlines that passed become `missed` Episodes, never silence; (b) the Developer Edition headless on a machine the user leaves on, paired to the Launcher; (c) **high-end:** a hosted watcher — the same module run server-side for feeds that hold no local secret — with the desktop keeping custody of anything credentialed. *Recommended:* (a) in the plan now; (b) works today by construction; (c) is a separate owner decision. Stage L1.

**Security**

- **W9 — ingested text reaches an agent turn** (deal titles, alert annotations, any scraped string — instruction injection). *Burden:* this is the most serious one: the module's purpose is to put outside data in front of an agent with tools. *Options:* (a) length caps and redaction on evidence; (b) evidence delivered as typed data with every free-text field fenced and labelled untrusted; (c) **high-end:** (b) plus a reduced tool admission for forged turns — read-only by default, declared per monitor — and a standing rule that an Episode whose evidence contains untrusted free text can never be eligible for an `act` level, with planted-instruction fixtures in the test corpus. *Recommended:* (c). Stage L2, and a precondition of ever lifting the `act` deferral (§2.6).
- **W10 — an agent-proposed feed points somewhere it should not** (`lens_propose`: internal addresses, the wrong product). *Burden:* the operator's seal must be an informed one. *Options:* (a) operator seal with the URL shown; (b) **high-end:** a real preview read before sealing, plus the network classifier Companion already has (`EterniaCompanion/packages/eternia_daemon/lib/src/monitor_http_transport.dart`): loopback, link-local and private ranges refused unless that binding was explicitly opted in, redirects re-classified, response size and time bounded. *Recommended:* (b), ported with the HTTP source. Stage L1 (classifier), L4 (proposal).
- **W11 — the push door on a desktop** (webhooks behind NAT; an open port). *Burden:* reachability and exposure. *Options:* (a) loopback and LAN only, for sources on the same network; (b) per-route secrets, timestamp and nonce replay protection, strict body caps; (c) **high-end:** a relay through the Eternia backend that authenticates and forwards and never judges, so the desktop holds an outbound connection and exposes nothing. *Recommended:* (a) + (b) for L3; (c) is a backend decision and is named, not assumed.
- **W12 — source credentials** (API keys for the user's own systems). *Burden:* the launcher's blend register holds Monitoring admission open on exactly this seam. *Options:* (a) environment variables; (b) **high-end:** opaque references in the manifest resolved from the hermes credential pool at read time, never in manifest bytes, never in evidence, scoped per feed, with a redaction test on every evidence path. *Recommended:* (b). Stage L1. Note for the launcher: with hermes as custodian the open question in `EterniaLauncher/docs/companion/planned/BLEND_DECISIONS_2026-09-23.md` ("Monitoring admission") changes shape and must be re-asked, not considered closed.

**Storage and presentation**

- **W13 — many feeds, unbounded growth** (watch anything). *Options:* (a) fixed retention; (b) **high-end:** Companion's refusal budgets ported as-is — a ceiling per monitor and per store, checked before a monitor is enabled, refusing the new definition rather than shortening retention or evicting another monitor (`EterniaCompanion/docs/decisions/0207-monitoring-local-manifest-custody.md`). *Recommended:* (b). Stage L1.
- **W14 — artifacts with no home** (agents generating artifacts from the data; hermes has no artifact store). *Options:* (a) a folder per Episode with media handles (in the plan); (b) **high-end:** a receipt-indexed artifact lifecycle — retention per monitor, superseded-by links when a later turn replaces a report, and export. *Recommended:* (a) now; (b) when artifacts are a browsed surface. Stage L2.
- **W15 — a chart kept apart from Lens grows its own data path** (charts in Generative UI). *Burden:* two authorities for one series. *Options:* (a) convention; (b) **high-end:** Companion's binding rule ported: a generated surface selects an opaque binding the host offered; it cannot supply observations, units, feed identities or actions, and reads only `runtime.lens.range` under a versioned series schema. *Recommended:* (b). It is the launcher Generative UI's contract to adopt; Lens publishes the schema at L1.
- **W16 — polling is not live** (live price chart). *Options:* (a) short cadence, stated; (b) **high-end:** a streaming feed kind with backpressure and store-side downsampling. *Recommended:* (a); (b) is in the later-decisions row.

## 6c. Idea under consideration — a scripting language (Luau) for Lens (owner, 2026-10-05)

**Not adopted. Recorded with its weak points per the §6b rule.** The owner is considering Lua or Luau and sees it as useful to Lens. Luau is already under audit for Generative UI behavior on the launcher side (`EterniaLauncher/docs/companion/planned/GENERATIVE_UI_BOUNDARY_AUDIT_2026-10-04.md`: a separate execution package, host-granted capabilities, no runtime chosen yet), so the question for Lens is not "which language" but "which host runs it".

**Measured 2026-10-05:** no Lua or Luau runtime or binding exists in hermes or the launcher. hermes's lock file already carries two pure-Python expression engines (`jmespath`, `jsonpath-python`). The phone bundle admits exactly one compiled distribution (`agent_runtime/bundle_profiles/bundled-phone.yaml`, `admitted_native`: pillow), and every bundle target is pinned to one CPython (`agent_runtime/bundle_profiles/interpreters.lock.json`), so a native script runtime is a wheel to build and admit per target.

**Where a script helps Lens, kept as two separate uses:**

| use | host | what the script does | new runtime needed |
|---|---|---|---|
| **display-side behavior over Lens data** — a derived series, a custom comparison, formatting, interaction in a generated surface | the launcher's Luau execution package (the audit's) | reads Lens through a host-granted capability over `runtime.lens.{range,latest,episodes}`; never writes | none beyond what Generative UI already plans |
| **watch-side logic** — extracting a value from a messy body, a rule the closed set (§3, §6a) cannot say | hermes, inside the poll path, with no UI and no launcher running | a pure function: body in, typed value out; or window in, decision out | a second Luau host, in Python |

**Position this plan takes:** adopt the first use as a contract now (Lens publishes the read capability; the launcher's Luau runtime consumes it when it exists). Defer the second: the watch path starts declarative (JMESPath-class expressions plus the closed rule set), behind a **transform port** — `extract(input) -> typed value`, `evaluate(window) -> decision` — so a script engine can be plugged in later without changing a manifest. Luau, not Lua, if a script engine arrives: one language across the platform, and its design starts from running untrusted code. Never both.

**Fixed whichever way it is ruled:** a Lens script is pure. It does not fetch, schedule, write the store or forge a turn; those stay the module's. It sees no clock and no randomness, so a rule can be replayed. Its exact bytes are part of the sealed manifest, so the operator seals the code that runs.

**Weak points this idea attaches**

- **W17 — untrusted code in the watch path** (a script written by the agent, possibly steered by ingested text, W9). *Burden:* the sandbox is now a security boundary the product owns. *Options:* (a) standard library stripped to pure functions; (b) plus instruction and memory limits with hard interruption, values copied in and out as plain data, no host objects reachable; (c) **high-end:** (b) inside a separate worker process (or a WebAssembly sandbox) that is killed on breach, script bytes sealed with the manifest and shown as a diff at every reseal, and a standing corpus of known escape attempts run on every engine upgrade. *Recommended:* (c). It is a precondition of the watch-side use, not a follow-up.
- **W18 — a native runtime in every bundle** (wheel per desktop target and per phone ABI, on the pinned CPython, under the vulnerability floor). *Burden:* build, admit and maintain a compiled distribution the bundle rules exist to keep out. *Options:* (a) no script engine in hermes; declarative expressions only; (b) a maintained Lua binding with published wheels — a different language from the launcher's; (c) a Luau binding built in CI for every target; (d) **high-end:** the script engine compiled to WebAssembly and hosted by one admitted runtime, so adding or upgrading an engine never adds a native wheel. *Recommended:* (a) through L4; decide (c) versus (d) by a measured spike (wheel size per target, cold start, interruption latency) only when a real journey needs watch-side scripts.
- **W19 — two hosts for one language** (the launcher's Luau package in Dart, a second in Python). *Burden:* two sandboxes, two limit implementations, two API surfaces that must agree — duplicated authority, the defect this stack keeps retiring. *Options:* (a) accept the divergence and document it; (b) one versioned script API contract with a shared conformance corpus both hosts must pass; (c) **high-end:** (b) plus one execution engine artifact both hosts load, so limits and built-ins are the same bytes. *Recommended:* (b) as the minimum bar for a second host; the launcher's package lands first and its API, limits and tests are the reference.
- **W20 — two ways to say one thing** (a script where a declarative rule would do). *Burden:* rules become opaque, unreviewable at a glance, and the agent reaches for code by default. *Options:* (a) convention; (b) **high-end:** a ladder enforced at proposal time — closed rule, then expression, then script — where `lens_propose` must name the rung below that was insufficient, and the sealed preview shows which rung a monitor uses. *Recommended:* (b).
- **W21 — a script keeps a monitor from being explained** (why did it fire?). *Options:* (a) log the output; (b) **high-end:** every observation and decision a script produced carries the script digest, its input window is retained with the Episode evidence, and the receipt can re-run it to the same answer. *Recommended:* (b); it follows from "no clock, no randomness" and costs little once that holds.

**Owed from the owner before any of this moves:** whether Luau is a platform-wide language decision (then it belongs in the parent brain, with Generative UI as the first host) or a Lens-only convenience (then the recommendation is no engine in hermes).

## 7. Provenance

Companion inventory and the hermes seam map were taken on 2026-10-01 from the two trees named in §1; the Companion product intent is `EterniaCompanion/output/home-release-gate/docs/plans/proposed/eternia-lens.md` §1, §5, §6, §10.5 (the thesis, the happy path, the scenario catalog, the three automation levels) and `docs/decisions/0207-monitoring-local-manifest-custody.md`. The hermes rulings applied are ADRs 0001, 0003, 0007, 0008, 0009 and the Fork Boundary Map's fence; the distribution vocabulary is the owner's 2026-09-29 naming ruling in `EterniaLauncher/docs/embedded_hermes/planned/README.md`.
