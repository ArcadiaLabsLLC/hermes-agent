# Planned — Lens W1 / W3 / W6 / W8 extensions and the missing-data rule (2026-10-27)

**Owner domain:** Lens (`agent_runtime/lens/`), parent plan [eternia-lens-in-hermes.md](eternia-lens-in-hermes.md)
§3 and §6b. **Status:** planned by lane w1027e-h-plan; build rows in `Harness_Brain/20 — Active
Initiatives/runtime-queue.md` (IDs per section below). Each section has the five headings; every choice
marked *Decided (plan)* is technical. The two owner questions are in §6.

Read on `main` 2026-10-27: `poller.py` (332 lines), `trigger.py` (281), `rules.py` (400), `episode.py`
(183), `manifest.py` (133), `sources/transport.py` (161), `store.py` (713 — 87 under the ADR 0007
ceiling, so every new table below lives in a new module that opens through `LensStore.connection()`).

Shared order: §5 (missing-data rule) and §4 (missed deadlines) both add to `episode.py`/`rules.py`;
§1 and §2 both add `ReadReason` members. None of these is a blocker, only a merge note.

---

## 1. W1 — source drift detection and reviewed repair (`RT-LENS-SOURCE-REPAIR`)

### Problem

A source that changes shape answers `selector_missing` / `not_a_number` / `not_json` /
`type_mismatch` / `no_series` / `ambiguous_series` gaps. Every rule then answers `unknown`, which
`episode.observe` treats as "no change" — so a broken feed is silence, told apart from a network blip
only by a human reading gap reasons. Nothing records what the source looked like when it worked, and no
turn is ever asked to repair it. `lens_propose` (`tool.py::propose_monitor`) refuses an existing
monitor (`StoreRefusal.EXISTS`), so a repair cannot reuse it as is.

### Decisions

1. **Shape fingerprint, not a raw sample.** *Decided (plan):* every answered read computes a shape
   skeleton — http_json/command: the JSON document's key paths with their JSON types (arrays collapsed to
   their first element, depth ≤ 8, ≤ 256 paths); prometheus: result type plus the sorted label-name set
   of each series; sql_readonly: the row's column names and declared types. The fingerprint is the sha256
   of the canonical skeleton. Retained per feed: the last KNOWN-GOOD skeleton (from a read that produced a
   value) and the newest DIFFERENT one, ≤ 4 KiB canonical each, in a new `feed_shapes` table. *Why not a
   raw body:* the transport's rule is that nothing a server sends reaches the store except a typed number;
   a skeleton carries no values, and the repair turn re-reads the live source itself through the preview
   read.
2. **Shape reasons are a typed set.** `SHAPE_REASONS = {selector_missing, not_a_number, not_json,
   type_mismatch, no_series, ambiguous_series}` beside `ReadReason`. Transport/availability reasons
   (`timeout`, `network`, `http_status`, `redirect_refused`, `too_large`, `private_address_refused`,
   `credential_missing`) are never shape drift.
3. **Broken = three consecutive shape-reason reads, or one shape-reason read whose fingerprint differs
   from the known-good one.** Three matches the L1 gate's own failure count; the fingerprint arm detects
   drift on the first bad read (W1(b)).
4. **Provenance: the sealed revision on every observation.** `observations` gains `revision INTEGER`
   (ALTER TABLE, like the `proposed` migration). Each feed has exactly one extractor today, so
   `(revision, feed_id)` names it. *Decided (plan): no extractor fallback chain for JSON sources.* The
   chain W1(c) describes (structured data → page metadata → selector) is a page-read concept and there is
   no page kind (`feed.FeedKind`); on a JSON API a fallback selector that lands on a different number is a
   silent wrong value. It belongs with the page adapter (`RT-LENS-PROVIDER-ADAPTERS`, deferred).
5. **`source_broken` is its own Episode.** Rule id reserved as `source_broken:<feed_id>` (`:` is legal in
   `wire_value._OPAQUE_ID`); `rules.read_rule` refuses the `source_broken:` prefix so a manifest cannot
   author it. Severity `attention`. It opens on decision 3, recovers on the next read whose value is
   present, and closes `closed_recovered` when a repaired revision's first read answers.
6. **Admission follows the monitor's level; `when: urgent` never hides a broken source.** In
   `LensForge.admit`, a `source_broken` Episode under `when: urgent` is settled `notified` (visible, no
   turn) instead of `skipped_severity`; under `level: investigate, when: always` it forges a repair turn.
   It counts toward `daily_turn_cap` like any receipt.
7. **The repair is a draft only the operator seals.** New tool `lens_propose_repair {monitor_id, feed_id,
   source}`: admitted only while that feed has an open `source_broken` Episode; replaces ONLY that feed's
   `source` block (rules, automation and other feeds byte-identical); runs one preview read that must
   answer a value; writes the next-revision draft through `store.create(..., proposal=True)` (the
   existing branch over a sealed monitor). Sealing stays `runtime.lens.seal`; dropping stays
   `runtime.lens.draft.drop`. It is not in `tool_permissions.READ_ONLY_BLOCKS`, so the read-only forged
   turn can call it — like `lens_propose`.

### Slices

| row | lands | files |
|---|---|---|
| `RT-LENS-SOURCE-REPAIR` | decisions 1–4: skeleton/fingerprint, `feed_shapes`, `revision` column, broken detection as a pure function | new `agent_runtime/lens/shapes.py`, new `agent_runtime/lens/store_shapes.py`, `agent_runtime/lens/sources/{http_json,prometheus,sql_readonly,command}.py`, `agent_runtime/lens/sources/transport.py`, `agent_runtime/lens/poller.py`, `agent_runtime/lens/store.py` (migration only) |
| `RT-LENS-SOURCE-BROKEN-EPISODE` | decisions 5–6 | `agent_runtime/lens/rules.py`, `agent_runtime/lens/poller.py`, `agent_runtime/lens/trigger.py`, `agent_runtime/lens/tool.py` (opening block: both skeletons inside the untrusted fence) |
| `RT-LENS-SOURCE-REPAIR-PROPOSE` | decision 7 | `agent_runtime/lens/tool.py`, `plugins/eternia-lens/__init__.py` |

*Built (`RT-LENS-SOURCE-REPAIR`, lane w1027f-h-lens-a), where the tree differed from the plan:*
`SHAPE_REASONS` is in `agent_runtime/lens/shapes.py` as the reasons' string values, not beside
`ReadReason` — `shapes.py` is a `models` module and `sources/transport.py` is `lanes`, so the enum
cannot be imported down; a test holds every member to a `ReadReason`. Python's `sqlite3` exposes a
column's name but not its declared type, so the SQL skeleton types each cell by its storage class.
The observation `revision` is written by `LensStore.record` itself (a subselect of the monitor's sealed
revision in the same INSERT) rather than threaded through the poller and the push door. The pure
detector is `shapes.source_broken`; `store_shapes.feed_broken` applies it to the stored facts and is
what slice 2 opens its Episode on.

*Built (`RT-LENS-SOURCE-BROKEN-EPISODE`, lane w1027g-h-lens):* the reserved rule is
`rules.source_broken_rule(feed_id)` — form `source_broken` (not a `RuleForm`, never sealed or
evaluated by `rules.evaluate`), severity `attention`; `rules.manifest_rule` resolves it for every
reader that looked a rule up by id (the exit door, both opening blocks). The poller moves it after
each pulled read on `store_shapes.drift_verdict` (FIRING while `feed_broken`, HEALTHY on a value,
else UNKNOWN); `closed_recovered` is decided by `store_shapes.repaired_since` — the recovering
read's observation `revision` is later than the one at the Episode's opening — so an operator's
manual re-seal counts as a repair too. The skeletons ride a SECOND untrusted fence,
`{<feed_id>: {known_good, newest}}`, after the source descriptions.

### Test plan

- Fingerprint: the same document with values changed → same fingerprint; a renamed key → different.
  Mutation: hash values into the skeleton → the first case reds.
- Broken: two shape-reason reads → not broken, the third → broken; three `timeout` reads → never broken
  (positive control for the typed set). Mutation: drop the `SHAPE_REASONS` filter → the timeout case reds.
- Episode: a manifest rule id `source_broken:x` is refused (mutation: remove the prefix check → red); an
  urgent-only monitor's broken feed gets `notified`, not `skipped_severity` (mutation: let the urgent
  filter run first → red).
- Repair: a proposal that also edits a rule is refused; with no open `source_broken` Episode it is
  refused; the stored draft differs from the sealed body only in that feed's `source`. Mutation: copy the
  caller's rules into the draft → red.

### Open questions

None for the owner. Launcher consumer (paint `source_broken` Episodes and the repair draft's one-feed
diff) is filed on the launcher side when `RT-LENS-SOURCE-REPAIR-PROPOSE` lands — the hermes half moves
first.

---

## 2. W3 — shared per-host read policy (`RT-LENS-HOST-READ-BUDGET`)

### Problem

Read pacing is per feed only: `_FeedClock.period` backs one feed off (×2…×8) and W7 floors deadline
cadence at `ADAPTIVE_FLOOR_MS`. Four monitors on one host read it four times as often; a `429` backs off
only the feed that saw it; `Retry-After` is ignored; an unchanged document is re-downloaded in full.

### Decisions

1. **Host key** = lowercase hostname + effective port of the URL a pulled HTTP source reads
   (`http_json`, `prometheus`, `via: kube_proxy`'s base URL). `sql_readonly`, `command_allowlisted` and
   `push` have no host and no budget.
2. **A token bucket per host, process-wide, in memory** (one poller per serve owns all reads). Defaults:
   public host 30 reads/min, burst 5; a feed that opted into `allow_private_network` 120/min, burst 20
   (an operator's own Prometheus is not a third party). Constants in a new `agent_runtime/lens/host_budget.py`;
   no manifest key (the manifest describes a monitor, the budget describes a host shared across monitors).
   *Built (w1027f-h-lens-b):* the bursts are constants there; the two rates are root-config knobs
   (`agent_runtime/lens/settings.py`, `agent_runtime.lens.host_reads_per_minute_{public,private}`) with these
   defaults, because §6 leaves them to the owner.
3. **A due read the bucket refuses is deferred, never dropped.** It is retried next tick. When the defer
   outlasts `rules.continuity_limit(interval)`, ONE gap is recorded with the new reason
   `host_budget_deferred` per elapsed interval, so the pause is visible in the series.
4. **`Retry-After` pauses the host.** On `429` or `503`, the transport parses `Retry-After` (delta-seconds
   or HTTP-date) to a bounded instant (≤ 1 h) and returns it on `ReadResult` as `retry_after_ms`; the
   poller pauses every feed on that host until then (deferred reads as in decision 3). Parsing a header to
   a bounded integer keeps the transport's rule that no header TEXT reaches the store.
5. **Conditional reads for `http_json`.** Per feed, in memory: the last `ETag` / `Last-Modified` and the
   last value. A `304` records an observation carrying that last value with reason `not_modified` (a new
   non-gap `ReadReason`) — the server asserted the representation unchanged at this time. After a restart
   there are no validators, so the first read is a full GET. Prometheus queries are not conditional.
6. **The poller identifies itself:** `User-Agent: EterniaLens/<package version>` on every HTTP read.
7. **Robots policy is the page adapter's, not this row's.** *Decided (plan):* robots rules govern
   crawling pages; Lens's built kinds read JSON APIs and Prometheus, where fetching `robots.txt` would add
   a read per host for no convention. When a page kind is approved (`RT-LENS-PROVIDER-ADAPTERS`), that
   adapter fetches `robots.txt` once per host per 24 h, honours `Disallow` for `EterniaLens`, and refuses
   with `robots_disallowed`. Nothing is built for it now.

### Slices

| row | lands | files |
|---|---|---|
| `RT-LENS-HOST-READ-BUDGET` | decisions 1–3, 6 | new `agent_runtime/lens/host_budget.py`, `agent_runtime/lens/poller.py`, `agent_runtime/lens/sources/transport.py` |
| `RT-LENS-HOST-RETRY-AFTER` | decision 4 | `agent_runtime/lens/sources/transport.py`, `agent_runtime/lens/host_budget.py`, `agent_runtime/lens/poller.py` |
| `RT-LENS-CONDITIONAL-READS` | decision 5 | `agent_runtime/lens/sources/transport.py`, `agent_runtime/lens/sources/http_json.py`, `agent_runtime/lens/poller.py` |

### Test plan

- Two monitors, one host, fake clock: reads in one minute ≤ the budget; a feed on another host is not
  slowed (positive control). Mutation: key the bucket by feed instead of host → red.
- A defer longer than the continuity limit records exactly one `host_budget_deferred` gap. Mutation:
  skip the gap → red.
- `429` with `Retry-After: 120` → no read on that host for 120 s, reads resume after. Mutation: pause only
  the feed → the sibling feed's read inside the window reds.
- `304` → an observation with the previous value and `not_modified`; a rule over it stays evaluable.
  Mutation: record `304` as a gap → red. Restart → no `If-None-Match` sent.

### Open questions

The default rates (decision 2) are a politeness number the owner may overrule; they are constants and
change with one line, so they do not block the build. See §6.

---

## 3. W6 — cooldowns, digests and a global model-turn budget (`RT-LENS-TRIGGER-COALESCING`)

### Problem

Kept (built): hysteresis (`recovery_threshold`), one Episode per breach with re-arm inside it, the 15 min
snooze, and the per-monitor `daily_turn_cap` (`store.receipts_today`). Missing: a rule that flaps
slower than its hysteresis opens a fresh Episode — and a turn — every time it re-breaches after settling;
many monitors breaching together each forge a turn; nothing bounds model spend across monitors.

### Decisions

1. **Two optional automation keys, absent = today's behaviour.** `cooldown_ms` (0…24 h) and
   `digest_window_ms` (0…6 h) join `manifest.AUTOMATION_KEYS` as OPTIONAL keys. `read_automation` emits
   them only when present, so every manifest sealed today keeps its canonical bytes and seal digest.
2. **Cooldown is per rule.** A new Episode of rule R whose admission falls inside `cooldown_ms` of R's
   previous receipt's `started_ms` is settled with the new outcome `cooled` — a receipt, visible in the
   fold, never a turn. The Episode itself still opens and records its facts.
   *Built (w1027f-h-lens-b):* "previous receipt" is the newest receipt of the rule that was not itself
   `cooled` (`agent_runtime/lens/store_admission.py::last_rule_receipt_ms`), so a rule flapping inside its
   cooldown is measured from the last admission that counted and is admitted again once it passes.
3. **Digest identity.** With `digest_window_ms > 0`, the first owed Episode of a monitor opens a window
   `[t, t + digest_window_ms)`; every Episode of that monitor owed inside it waits. At window end ONE turn
   (or one notify) carries all of them. `digest_id = canonical_digest({monitor_id, window_start_ms})`;
   `turn_id = lens_client_message_id(digest_id)`. `receipts` gains a nullable `digest_id`; every member
   Episode gets its own receipt row with the shared `turn_id`, outcome `digested` for members and the
   ordinary outcome for the leader (the earliest). The once-only guarantee holds per digest: all member
   receipts are written in the same transaction, before the turn. The digest opening block lists each
   member's evidence under the existing 32 KiB budget, halving per member as `_evidence` does.
   *Built (w1027f-h-lens-b):* the window lives in `digest_windows` (`agent_runtime/lens/store_digests.py`) and
   closes in the transaction that writes every member receipt (`LensStore.save_receipts(..., also=...)`). The
   per-Episode screen (rule, cooldown, urgency) runs before the window, so a cooled or skipped Episode never
   joins one; cap, budget and level are decided once for the digest. Each member's evidence is built to an
   N-th of the 32 KiB budget. `receipts_today` is unchanged: members carry `digested`, which the cap does not
   count, so a digest is one turn without counting distinct `turn_id`s. The turn and its chat are keyed by
   `digest_id` (`forge_episode_turn(turn_key=...)`), the folder and the artifact list by the leader.
4. **Global budget, per UTC day, across monitors.** Runtime config key `lens.daily_turn_budget`
   (read through `agent_runtime/config/loader.py::load_agent_runtime_config`; default in §6). A turn — a digest
   counts once — that would exceed it is downgraded to a notify with outcome `notified_over_budget`, never
   dropped. `receipts_today` counts distinct `turn_id`s, so a digest is one turn for the per-monitor cap too.
   *Built (w1027f-h-lens-b):* read raw from the root config (`agent_runtime/lens/settings.py`, default 96), not
   through `load_agent_runtime_config` — a `RuntimeConfig` section rides the `runtime_config` wire via
   `asdict(cfg)`. The budget counts receipts whose `tool_admission` is `read_only` (a turn begun), all monitors,
   UTC day (`agent_runtime/lens/store_admission.py::turns_today`); `notified_over_budget` joins the per-monitor
   cap's counted outcomes like `notified`.
5. **Order inside `admit`:** rule-not-in-revision → cooldown → urgency filter → per-monitor cap → global
   budget → level. Cooldown first because a cooled Episode must not spend cap.

### Slices

| row | lands | files |
|---|---|---|
| `RT-LENS-TRIGGER-COALESCING` | decisions 1 (`cooldown_ms`), 2, 5 | `agent_runtime/lens/manifest.py`, `agent_runtime/lens/trigger.py`, `agent_runtime/lens/store.py` (`ReceiptOutcome.COOLED`) |
| `RT-LENS-GLOBAL-TURN-BUDGET` | decision 4 | `agent_runtime/lens/trigger.py`, `agent_runtime/lens/store.py` |
| `RT-LENS-DIGEST-WINDOW` | decisions 1 (`digest_window_ms`), 3 | `agent_runtime/lens/manifest.py`, `agent_runtime/lens/trigger.py`, new `agent_runtime/lens/store_digests.py`, `agent_runtime/lens/tool.py` |

### Test plan

- A sealed manifest without the new keys keeps its digest byte-for-byte (golden from a fixture sealed on
  today's code). Mutation: emit `cooldown_ms: 0` by default → red.
- Breach, settle, re-breach inside the cooldown → `cooled`, no forge call; outside → forged (positive
  control). Mutation: skip the cooldown check → red.
- Over budget across two monitors: the N+1th turn is `notified_over_budget` and the notify still happens.
  Mutation: return `None` (no receipt) instead → red.
- Three Episodes inside one digest window → one forge call, three receipts, one `turn_id`; a restart
  mid-window forges nothing twice. Mutation: write member receipts after the turn → the restart case reds.

### Open questions

The budget default is the owner's (model spend) — §6. The mechanism builds with any default.

---

## 4. W8 — missed deadlines while the watcher was off (`RT-LENS-MISSED-DEADLINES`)

### Problem

`LensPoller.catch_up` records one `watcher_offline` gap per unwatched feed. An `ends_within` deadline
whose lead window opened and closed while the serve was down produces nothing: on resume the latest row
is the offline gap (`unknown`), and if the source has since dropped the item, every later read is a gap
too. The deadline passes in silence — the exact outcome W8(a) forbids.

### Decisions

1. **A missed deadline is derived only from recorded facts.** In `catch_up`, per enabled `ends_within`
   rule: D = the newest NON-GAP value of its instant feed recorded before the offline interval; the
   offline interval is `(that feed's latest observed_ms, now)`. If `D - window_ms` (when the rule would
   have fired) or D itself falls inside the offline interval, and D ≤ now, a missed Episode opens. No
   observation is written for the unwatched interval beyond the existing `watcher_offline` gap.
2. **New Episode state `missed`**, version-2 Episode rows with an optional `missed_deadline_ms = D`
   (`Episode.from_json` accepts version 1 unchanged). `first_seen` = max(`D - window_ms`, offline start),
   `last_seen` = D, `count` = 1. `needs_admission` admits `missed` like `active`; `observe` treats a
   `missed` previous as not open, so a later real breach gets the next ordinal.
3. **Deduplication:** no missed Episode when the rule's latest Episode already has `last_seen ≥ D -
   window_ms` (it fired before the outage), or a missed Episode with the same `missed_deadline_ms`
   exists (a second restart). Pure function, one query per rule.
4. **A deadline still ahead on resume is not missed** — the normal tick and its W7 confirming read fire
   it from a fresh read.
5. **The opening block says what is known and what is not:** offline from X to Y, the recorded deadline
   D passed inside it, no read was made in that interval, the current value is unknown until the next
   read. Admission otherwise follows `LensForge.admit` unchanged.

### Slices

| row | lands | files |
|---|---|---|
| `RT-LENS-MISSED-DEADLINES` | decisions 1–5 (one slice: the state, its producer and its opening block are not separable without an unproduced state) | `agent_runtime/lens/episode.py`, `agent_runtime/lens/poller.py`, `agent_runtime/lens/trigger.py`, `agent_runtime/lens/tool.py`, `agent_runtime/lens/snapshot_fold.py` |

*Built (`RT-LENS-MISSED-DEADLINES`, lane w1027f-h-lens-a), where the tree differed from the plan:* the
producer and its queries are a new `agent_runtime/lens/missed_deadlines.py` (the poller only calls
it from `catch_up`). Decision 3's two dedup arms are ONE check: a `missed` Episode's `last_seen` is D,
so "a missed Episode for the same D exists" already satisfies "the latest Episode was seen at or
after D − lead"; the separate query had no killing mutation and was dropped. Decision 1's "D − lead
or D inside the outage, and D ≤ now" reduces to offline_from < D ≤ now. The outage the opening block
names is read back from the recorded rows (the first `watcher_offline` gap at or after D, and the row
before it), not stored on the Episode, so the version-2 row adds only `missed_deadline_ms`. Push
feeds are not caught up (as before), so a push-fed deadline is never `missed`. Follow-ups filed:
`RT-LENS-MISSED-THEN-FIRED`, `RT-LENS-EPISODE-DECIDE-VERB`.

### Test plan

- Deadline recorded, serve down across D, resume after D → exactly one `missed` Episode with
  `missed_deadline_ms = D`; a second `catch_up` → still one. Mutations: drop the dedup query → two; use
  the resume time as the deadline → the `missed_deadline_ms` assertion reds.
- Positive control: deadline still ahead at resume → no `missed` Episode, the tick opens a normal one.
- Rule fired before the outage → no `missed` Episode. No new observation rows besides the
  `watcher_offline` gap (row count before/after).

### Open questions

None for the owner. The launcher reads Episode `state` as a string
(`EterniaLauncher/lib/core/services/hermes/runtime/data/snapshot/harness_lens_fold.dart`), so `missed`
does not break it; painting it distinctly is a launcher row filed when this lands.

---

## 5. The missing-data rule (`RT-LENS-MISSING-DATA-RULE`)

### Problem

Parent plan §3's `rules.py` row promises "missing-data rules". Today missing evidence answers `unknown`
by design — "I cannot judge" — and `unknown` never opens an Episode. That is right for value rules and
wrong for the case where the ABSENCE is the alert (a heartbeat push that stopped, an exporter that went
dark). The rule must fire on attested absence without making `unknown` mean "breach".

### Decisions

1. **New form `missing_data`** in `rules.RuleForm`: `feed_id`, `window_ms` (≥ the feed's
   `continuity_limit(interval)`, ≤ 24 h, checked in `manifest._check_typed_rules` where intervals are
   known), `direction: below`, `threshold: 0` (the `ends_within` convention), `samples: 1`;
   `confirm_reads` and `recovery_threshold` other than 0 refused.
2. **Absence must be attested.** Gap reasons split into ATTESTING (the watcher asked and got no value:
   every read-failure reason, `ingress_refused`) and NON-ATTESTING (nobody could ask: `watcher_offline`,
   `not_sealed`, `push_only`, and `host_budget_deferred` from §2). Verdict at `now`:
   - FIRING — no valid observation in `(now - window_ms, now]`, AND the watch covered the whole window:
     for a pulled feed, attesting rows across it with no hole wider than the continuity limit and no
     non-attesting row; for a `push` feed, the ingress listener bound continuously since ≤ `now -
     window_ms`.
   - HEALTHY — a valid, current observation inside the window.
   - UNKNOWN — anything else (a non-attesting gap, a listener that was down, a watcher that started
     inside the window). This is the existing `unknown`, unchanged in meaning.
3. **A clock form.** `missing_data` joins `rules.CLOCK_FORMS`, so `_clock_rules` evaluates it every tick
   — a silent push feed records no rows, and only the clock can notice. The pure evaluator takes a
   `watched_since` instant from the caller; the poller passes `WATCHER.since` for pulled feeds and the
   listener's new `bound_since` (`agent_runtime/lens/ingress.py::ingress_state`) for push feeds. The W7
   confirming read does not apply (a confirming read of a missing source is just another attesting gap).
4. **Recovery** is the first valid current observation → HEALTHY → the Episode goes `recovered`;
   resolution stays the operator's.

### Slices

| row | lands | files |
|---|---|---|
| `RT-LENS-MISSING-DATA-RULE` | decisions 1, 2, 4 — the form and its pure evaluator, with conformance cases | `agent_runtime/lens/rules.py`, `agent_runtime/lens/manifest.py`, `tests/agent_runtime/lens/conformance/` |
| `RT-LENS-MISSING-DATA-CLOCK` | decision 3 — poller clock wiring and the listener's `bound_since` | `agent_runtime/lens/poller.py`, `agent_runtime/lens/ingress.py` |

*Built (`RT-LENS-MISSING-DATA-RULE`, lane w1027f-h-lens-a), where the tree differed from the plan:*
the evaluator needs each gap's reason and `feed.Observation` carried none, so `Observation` gained an
optional `reason` (off `to_json`, out of equality). `rules.evaluate` routes `missing_data` to
`rules.evaluate_missing_data` and takes `watched_since` / `pushed` keywords; without `watched_since` the
form answers HEALTHY or UNKNOWN, never FIRING — so until slice 2 a sealed `missing_data` rule recovers
but cannot fire. The attesting/non-attesting split is two explicit string sets in `rules.py` (a gap
with no reason, or one in neither set, attests nothing); a test enumerates `ReadReason` against them,
exempting the value-carrying `ok` / `not_modified`. `missing_data` is admitted on instant feeds. The
corpus is `tests/agent_runtime/lens/conformance/missing_data_corpus.json` (hermes-authored, 12 cases).
**Slice 2 must** build the poller's observations with `reason=row["reason"]` (today `_verdict` drops
it, which makes every gap non-attesting) and pass `watched_since` / `pushed`.

### Test plan (conformance cases, each one JSON case in the corpus)

1. Valid reads, then attesting failures spanning more than `window_ms` → FIRING.
2. Same, window not yet elapsed since the last valid read → HEALTHY.
3. A `watcher_offline` gap inside the window → UNKNOWN (mutation: count it as attesting → red).
4. Push feed silent, listener bound across the window → FIRING; listener bound inside the window →
   UNKNOWN (mutation: ignore `watched_since` → red).
5. One valid read after FIRING → HEALTHY (recovery).
6. A sample later than `now` → UNKNOWN.
7. Never any valid read, attested window → FIRING.
8. Positive control for 3: the same series with the offline gap replaced by a `timeout` gap → FIRING.
Manifest: `window_ms` below the continuity limit is refused (mutation: drop the check → red).

### Open questions

None for the owner.

---

## 6. Owner questions (non-blocking; each has a default the build uses)

1. **Global Lens turn budget per day (§3 decision 4).** Options: (a) 96 — the ceiling one monitor may
   already spend, so the budget only bites with several monitors; (b) 48; (c) off by default.
   **Recommend: (a) 96**, configurable, with the downgrade visible as `notified_over_budget`.
2. **Per-host read rates (§2 decision 2).** Options: (a) 30/min public, 120/min private; (b) stricter
   (6/min public). **Recommend: (a)** — W7's own floor is one read per 5 s per feed, and the budget is
   shared across monitors on the host.
