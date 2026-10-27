# Planned — Lens: missed-then-fired, scheduled runs, equivalence evidence, the reply report (2026-10-27)

**Owner domain:** Lens (`agent_runtime/lens/`), parent plan [eternia-lens-in-hermes.md](eternia-lens-in-hermes.md)
(§4 `monitor_insights` row, §6a, W5, W9, W14) and today's [LENS_EXTENSIONS_2026-10-27.md](LENS_EXTENSIONS_2026-10-27.md)
§4. **Status:** planned by lane w1027j-h-plan; build rows in `Harness_Brain/20 — Active Initiatives/runtime-queue.md`
(IDs per section). Every *Decided (plan)* choice is technical; the one owner question is in §4.

Read on `main` 2026-10-27 (`282bf59907`): `rules.py` (499 lines), `poller.py` (444), `trigger.py` (454),
`tool.py` (385), `manifest.py` (153), `feed.py` (489), `episode.py` (206), `missed_deadlines.py` (85),
`artifacts.py` (138), `store.py` (799 — at its ceiling, `RT-LENS-STORE-AT-CEILING`; nothing below adds to it).

Shared order: §1 and §2 both touch `poller.py` and `episode.py`; §2 and §4 both touch `trigger.py::_forge`
neighbours and `tool.py::_block`; §3 and §2 both touch `manifest.py`. None blocks another; land them in
different waves or as one lane.

---

## 1. One deadline, one admission (`RT-LENS-MISSED-THEN-FIRED`)

### Problem

`missed_deadlines.missed_episode` opens a `missed` Episode for a deadline D that passed while the watcher
was off. `episode.is_open` answers False for `missed` (by design: "the next real breach is the next
ordinal"). On resume the first fresh read of the feed still answers D, `rules._ends_within` answers FIRING
for any deadline at or behind `now` (`deadline - now <= window` holds for every negative remainder), and
`episode.observe` — seeing a previous that is not open — opens ordinal N+1 `active`. `LensForge` admits
both: two turns, two chats, one deadline. `poller._would_open` also spends a confirming read on it.

### Decisions

1. **A read of the deadline a `missed` Episode names IS that Episode.** *Decided (plan):* W8(a) says a
   passed deadline "becomes a `missed` Episode", once; W6 exists so one fact never costs two turns. The
   read adds nothing the missed turn did not already say (the deadline passed). A DIFFERENT instant
   (the listing was extended or relisted, D2 ≠ D) is a new deadline and keeps today's behaviour.
2. **The test is exact equality of the recorded instant** (`value == missed_deadline_ms`). Instants are
   typed integral epoch milliseconds (`feed.py`, W2(c)), so equality is well defined; any tolerance would
   merge two real deadlines.
3. **`_ends_within` is NOT changed to answer HEALTHY behind `now`.** *Decided (plan):* (a) it would flip
   every ordinary `active` deadline Episode to `recovered` the moment its auction ends — a visible
   semantic change to every existing `ends_within` monitor that this row does not need; (b) a first-ever
   read of an already-passed deadline would become silence, the outcome W8 forbids. The defect is that
   `missed` is not open, so the fix sits where `missed` is consulted, not in the rule.
4. **One guard, two call sites, in `poller.py`:** `_evaluate.step` returns `previous` unchanged, and
   `_would_open` answers False (no confirming read), when the rule is `ends_within`, `previous` is
   `missed`, and the feed's newest non-gap value equals `previous.missed_deadline_ms`. The predicate is a
   pure function `continues_missed(previous, deadline_ms)` in `missed_deadlines.py` beside
   `missed_episode`; the newest-value query reuses that module's `_recorded_deadline` (made public as
   `recorded_deadline`). A settled (dismissed) `missed` Episode is still that deadline: no re-fire.

### Slices

| row | lands | files |
|---|---|---|
| `RT-LENS-MISSED-THEN-FIRED` | decisions 1–4 | `agent_runtime/lens/missed_deadlines.py`, `agent_runtime/lens/poller.py`, `tests/agent_runtime/lens/test_lens_missed_deadlines.py` |

### Test plan

- Missed Episode for D (the existing fixture), then a fresh read answering D, then `tick()` → still ONE
  Episode for the rule (ordinal 1, `missed`), one receipt after `LensForge.tick()`. *Killing mutation:*
  delete the guard in `_evaluate.step` → ordinal 2 `active` appears, red.
- Same fixture: the tick's returned confirming-read count is 0. *Killing mutation:* delete the guard in
  `_would_open` → the tick makes a confirming read (count 1, one more observation row), red.
- Positive control (same bytes, one variable): the fresh read answers D2 = now + lead/2 → ordinal 2
  `active` opens and is admitted. Proves the fixture reaches the firing path, so the two negative
  assertions above are not vacuous.
- Settled control: the `missed` Episode dismissed, read answers D → still no ordinal 2.

### Open questions

None for the owner. Not filed, noted: an `active` deadline Episode past its deadline keeps counting
(`count + 1` per clock tick) until the source changes; it is admitted once, so nothing user-visible moves.

---

## 2. Scheduled runs — the `schedule:` field (`RT-LENS-SCHEDULED-INSIGHTS`, `RT-LENS-SCHEDULE-PROPOSE`)

### Problem

The parent plan cut Companion's `monitor_insights*` to "one field, not a module": a manifest may carry
`schedule:` and the same `trigger.py` forges the turn (§4); discovering new listings is "a scheduled agent
turn … capped by `daily_turn_cap`" (§6a). The field does not exist: `manifest.MANIFEST_KEYS` is closed and
has no `schedule`, and nothing produces a turn on a clock.

### Decisions

1. **Schema (optional top-level key, absent = today's bytes).** *Decided (plan):*
   `schedule: {every_ms, offset_ms, brief}` — `every_ms` in [15 min, 7 d] (15 min is the
   `MAXIMUM_DAILY_TURN_CAP` = 96 floor), `offset_ms` in [0, `every_ms`) (the phase in UTC: daily at 08:00
   UTC is `every_ms` 86 400 000, `offset_ms` 28 800 000), `brief` a bounded plain string ≤ 1 024 chars —
   the standing ask ("look for new listings of X under Y"). Read like the W6 optional automation keys:
   emitted only when present, so every sealed digest is unchanged. Interval-plus-phase, not cron: one
   integer pair is closed, canonical and needs no parser.
2. **Seal-time refusals** (in `read_manifest`, so a draft shows them too): `schedule_needs_investigate`
   (a `notify` schedule forges nothing, so it is meaningless); `schedule_over_cap` when
   `ceil(86 400 000 / every_ms) > daily_turn_cap` (a schedule the cap would clip every day is refused, not
   silently capped). `investigate` already requires `persona_id` at seal (`check_sealable`).
3. **A run is an Episode of a reserved rule**, `schedule:run`, resolved by `rules.manifest_rule` exactly as
   `source_broken:<feed_id>` is (`rules.source_broken_rule`): never sealed, never evaluated, its
   `feed_ids` every feed of the monitor, `window_ms` = min(`every_ms`, 24 h), severity `attention`.
   *Why an Episode and not a new table:* receipts, the daily cap, the global budget, pause, the read-only
   chat, retention and the receipt fold already key on Episodes; a parallel run record would be a second
   admission path. `_authored_id` refuses the `schedule:` prefix as it refuses `source_broken:`.
4. **New Episode state `scheduled`** (version 1 row; `from_json`'s missed/version-2 pairing is
   untouched). In `ADMITTED_STATES`, never open (`is_open` False), and not in
   `store_decisions._OPEN`, so it is never painted as an alert on the fold's `open_episodes`; the receipt
   is its record. Retention's `state != 'active'` sweep already reaps old ones and keeps the newest.
5. **Clock and idempotency.** The current slot starts at `S = floor((now - offset) / every) * every +
   offset`. A run is due iff the rule's latest Episode is None or its `first_seen < S`. The run's
   `ordinal` is previous + 1, `first_seen` = S, `last_seen` = now (lateness is `last_seen - first_seen`).
   Keying "due" on the slot start rather than on a slot-index ordinal keeps it correct when a reseal
   changes `every_ms`. A second tick in the same slot finds `first_seen == S`: nothing. Produced by a new
   `agent_runtime/lens/schedules.py` (pure `scheduled_episode(...)` + `record_due_schedule(store, …)`),
   called once per enabled monitor per `LensPoller.tick` — the poller already iterates enabled monitors
   only, so a paused monitor accrues nothing.
6. **Catch-up: one late run, never a storm.** After an outage (or a pause) spanning several slots only the
   CURRENT slot is due, so resume forges at most one run, late; the skipped slots are not materialised.
   The opening block states the previous run's time (the prior Episode's `first_seen`, or "none
   recorded") so the gap is visible, never silent. First enable: the current slot is due at once (one run
   on enable, then one per slot) — no seal timestamp is stored to do otherwise without a `store.py` change.
7. **Admission through the existing door** (`LensForge.admit`): the urgency filter and `cooldown_ms` do
   not apply to `schedule:run` (they govern breaches; the sealed schedule is the operator's explicit ask
   and its spacing is its own cooldown); the daily cap and the global budget DO apply (`capped` /
   `notified_over_budget`, visible); a scheduled run never joins a W6 digest (`_digest` and `_owed` skip
   it) — a digest merges evidence, and merging a standing ask into an alert turn mixes two instructions.
8. **Its opening block** (`tool.schedule_opening_block`): header `[LENS SCHEDULED RUN — <monitor> · #n]`;
   the sealed `brief` labelled as the operator-sealed ask (it is sealed manifest bytes, not ingested text,
   but it is still shown inside a labelled section, not as system text); typed data (slot start, run time,
   previous run, each feed's latest evidence window); the instruction that new things to watch go through
   `lens_propose` (a draft the operator seals). The turn is read-only like every forged turn
   (`lens_propose` and the web/read tools are not in `tool_permissions.READ_ONLY_BLOCKS`).
9. **`lens_propose` accepts `schedule`** (slice 2): the agent that set up the watch can propose its
   discovery schedule; the operator seals it with everything else.

### Slices

| row | lands | files |
|---|---|---|
| `RT-LENS-SCHEDULED-INSIGHTS` | decisions 1–8 (the field, its producer and its admission are not separable: a produced `scheduled` Episode the door cannot word is a defect) | `agent_runtime/lens/manifest.py`, `agent_runtime/lens/rules.py`, `agent_runtime/lens/episode.py`, new `agent_runtime/lens/schedules.py`, `agent_runtime/lens/poller.py`, `agent_runtime/lens/trigger.py`, `agent_runtime/lens/tool.py`, new `tests/agent_runtime/lens/test_lens_schedules.py` |
| `RT-LENS-SCHEDULE-PROPOSE` | decision 9 | `agent_runtime/lens/tool.py` (`LENS_PROPOSE_SCHEMA`, `propose_monitor`), `tests/agent_runtime/lens/test_lens_pull_door.py` |

### Test plan

- Manifest without `schedule` → canonical bytes and seal digest byte-equal to today's (fixture digest
  pinned). *Killing mutation:* emit `schedule: null` when absent → digest red.
- `notify` + schedule → `schedule_needs_investigate`; `every_ms` 3 600 000 with cap 5 → `schedule_over_cap`.
  *Mutation:* drop either check → that case accepts, red. Positive control: cap 24 accepts.
- Clock: two ticks in one slot → one Episode; a tick in the next slot → ordinal 2 with `first_seen` = its
  slot start. *Mutation:* compare `first_seen <= S` → the second same-slot tick opens ordinal 2, red.
- Catch-up: latest run 3 slots ago, tick now → exactly one new Episode (current slot) and the opening
  block names the previous run's time. *Mutation:* materialise one run per missed slot → three, red.
- Reseal daily → hourly → the next hourly slot is due (slot-index ordinals would wait ~days). *Mutation:*
  ordinal = slot index → red.
- Door: a `when: urgent` monitor's run forges (positive control: an `attention` breach rule on the same
  monitor is `skipped_severity`); cap reached → `capped`; digest monitor → the run is its own turn while a
  breach waits in the window. *Mutation per arm:* remove the exemption / the digest skip → red.
- Fold: a `scheduled` Episode is absent from `open_episodes`. *Mutation:* add it to `_OPEN` → red.
- Slice 2: `lens_propose` with a `schedule` drafts it; a `notify` proposal with one is refused.

### Open questions

Non-blocking (the build uses the default): local-time schedules with DST ("every morning at 8 my time")
are not expressible — the default is UTC interval-plus-phase; the Launcher's authoring form can convert a
local time once at authoring. Filed for the Launcher (report, verbatim): the authoring form's schedule
fields and a "scheduled run" label on receipts.

---

## 3. W5 equivalence — labels at seal, justification at proposal (`RT-LENS-EQUIVALENCE-LABELS`, `RT-LENS-EQUIVALENCE-PROPOSAL`)

### Problem

`manifest._check_typed_rules` admits a `best_of` group when every member has the same comparable type
(`feed.comparable_type`: kind + stored currency). Typed totals (price + shipping + tax at a dated FX rate)
are built. Nothing says the members are the same PRODUCT: a used and a new unit, a 128 GB and a 256 GB
variant, or two different models in one currency are "comparable" today, and `best_of` then reports a
"better deal" that is wrong, not approximate (W5). `lens_propose` (`tool.propose_monitor`) carries no
reason why the agent grouped the listings, so the operator seals the group blind.

### Decisions

1. **Product labels on the feed, sealed.** *Decided (plan):* optional feed key `product:
   {identity, variant, condition}` (`FEED_KEYS_OPTIONAL`; absent = today's bytes). `identity` a bounded
   string ≤ 128 (a GTIN/MPN when known, else a normalised model name), `variant` ≤ 64 (capacity, colour,
   size; `""` when the product has none), `condition` a closed enum `new | used | refurbished | open_box |
   for_parts | unknown` — an explicit `unknown`, never an absent meaning "new".
2. **The group rule, at SEAL, for money groups only.** *Decided (plan):* in `manifest.check_sealable`
   (the seal-only gate, `seal.py`), not `read_manifest`: a `best_of` whose group is `money` requires every
   member to carry `product`, and all members to share `condition` and `variant` (case-folded) —
   refusal `equivalence_unlabelled` / `equivalence_mismatch`. Seal-time so every already-sealed revision
   keeps reading; money-only because a `best_of` over plain numbers (latency across regions) is not a
   product comparison. `condition: unknown` on any member is refused in a money group (an unknown
   condition cannot be shown to match). `identity` is NOT required equal: marketplaces spell one product
   differently, and that judgement is decision 3's.
3. **Justification is proposal evidence, not sealed bytes.** *Decided (plan):* `lens_propose` takes an
   optional `equivalence: {<feed_id>: {why, cited}}` — `why` ≤ 512 chars, `cited` ≤ 4 short strings the
   agent read (a listing's title, its item specifics). A proposal whose rule is a money `best_of` is
   refused `equivalence_unjustified` without one entry per member. Stored in a NEW module
   `agent_runtime/lens/store_proposals.py` (table `proposal_evidence (monitor_id, draft_digest, body)`,
   through `LensStore.connection()`, as `store_shapes.py` does) keyed by the draft's canonical digest, and
   returned by `runtime.lens.get` as `equivalence_evidence` with `stale: true` once the operator edits the
   draft (digest differs). Not sealed: the text is source-derived (W9), so it is shown to the operator
   inside the untrusted fence, never executed or re-fed to a turn as instruction.
4. **The operator's own `runtime.lens.create` needs labels (decision 2) but no justification** — the
   operator is the authority the justification exists to inform.
5. **The opening block** of a `best_of` Episode includes each member's `product` labels as typed data,
   so the investigate turn sees what was claimed equal.

### Slices

| row | lands | files |
|---|---|---|
| `RT-LENS-EQUIVALENCE-LABELS` | decisions 1, 2, 4, 5 | `agent_runtime/lens/feed.py`, `agent_runtime/lens/manifest.py`, `agent_runtime/lens/tool.py` (`_typed_feeds`), `tests/agent_runtime/lens/test_lens_journey_rules.py` |
| `RT-LENS-EQUIVALENCE-PROPOSAL` | decision 3 (needs decision 1's labels) | `agent_runtime/lens/tool.py`, new `agent_runtime/lens/store_proposals.py`, `agent_runtime/serve_rpc/lens.py` (`runtime.lens.get`), `tests/agent_runtime/lens/test_lens_pull_door.py` |

### Test plan

- A sealed money `best_of` without labels still READS (old revision) but a reseal refuses
  `equivalence_unlabelled`. *Killing mutation:* move the check into `read_manifest` → the stored-revision
  read reds; drop it → the reseal accepts, red.
- `new` vs `used` members → `equivalence_mismatch`; positive control: both `new`, same variant → seals.
  *Mutation:* compare `identity` instead of `condition` → the mismatch case seals, red.
- A number-kind `best_of` without labels seals (control that the rule is money-only).
- Feed without `product` → canonical bytes unchanged (digest pinned).
- Proposal: money `best_of` without `equivalence` → `equivalence_unjustified`; with it → `runtime.lens.get`
  returns it; operator `runtime.lens.create` over the draft → `stale: true`. *Mutation:* key evidence by
  monitor id only → `stale` stays false, red.

### Open questions

None for the owner: W5's recommended (b) — "best_of allowed only inside a declared equivalence group
whose membership the agent justified at proposal time and the operator sealed" — is applied as written;
a buyer who wants "new or used, whichever is cheapest" seals two rules, one group each. Filed for the
Launcher (report, verbatim): show `product` labels and `equivalence_evidence` in the seal review.

---

## 4. The reply report under read-only admission (`RT-LENS-ARTIFACT-REPLY-REPORT`, `RT-LENS-ARTIFACT-LIVE-PROOF`, `RT-LENS-ARTIFACT-WRITE-TOOL`)

### Problem

`tool._block` tells the forged turn "Write any file you produce (a report.md, a chart) into this folder".
The turn cannot: owner RULED 2026-10-22 (`RT-LENS-FORGED-TURN-TOOL-ADMISSION`, built `79e006e701`) holds
the Episode chat `read_only`, which blocks `write_file`, `patch`, `terminal` (`tool_permissions.READ_ONLY_BLOCKS`)
and drops the code-execution toolsets (the 2026-10-25 live record:
[live-sitting-results-2026-10-25.md](live-sitting-results-2026-10-25.md), `toolsets_dropped [terminal,
browser, vision, code_execution]`). So `artifacts.collect`'s `files` list is always empty live, and
`test_lens_exit_door.py::test_a_turn_that_wrote_report_md_lists_it_on_the_receipt` passes only because its
fake turn writes the file from outside the permission store — a capture that carries a write the real
turn cannot make.

### Decisions

1. **The door writes the reply as `report.md`; the turn writes nothing.** *Decided (plan):* plan §2.2
   already says "the persona's reply and any files it writes are the artifact". After the turn,
   `trigger._forge` hands the reply text to a new `artifacts.write_reply_report(episode_id, reply)`
   BEFORE `collect`, so the receipt lists it and `runtime.lens.artifact` serves it unchanged. No tool is
   admitted, no permission is relaxed, the RULED read-only admission is untouched.
2. **Bounds:** UTF-8, exclusive create (an existing `report.md` is kept: a re-entered turn never
   overwrites), at most `MAXIMUM_ARTIFACT_BYTES` — a longer reply is cut on a character boundary with a
   final `[truncated: N bytes]` line so `read_artifact`'s size refusal never fires on our own file; no
   file when the reply is empty or the turn failed with no reply. A digest's report is in the leader's
   folder (the turn's folder).
3. **The opening block stops asking for files:** the folder sentence becomes "Your reply is saved as
   report.md in this Episode's folder and listed on the receipt; this turn is read-only, so do not try to
   write files." The `MEDIA:` sentence is dropped (the turn cannot create an image); `mint_reply_media`
   still runs in `collect`, unchanged.
4. **Richer artifacts (CSV, charts) need a write the ruling forbids** — that is the owner's question below,
   filed as its own row, and not needed for the report journey.

### Slices

| row | lands | files |
|---|---|---|
| `RT-LENS-ARTIFACT-REPLY-REPORT` | decisions 1–3 | `agent_runtime/lens/artifacts.py`, `agent_runtime/lens/trigger.py` (`_forge`), `agent_runtime/lens/tool.py` (`_block`), `tests/agent_runtime/lens/test_lens_exit_door.py` |
| `RT-LENS-ARTIFACT-LIVE-PROOF` | the live check only, after the build | none — read live (below) |

### Test plan

- Fake forge returns `reply: "# cpu\n…"` and writes nothing → receipt `files` lists `report.md` with the
  reply's size and sha256; `runtime.lens.artifact` returns the reply text. *Killing mutation:* drop the
  `write_reply_report` call → `files` empty, red. Re-point the existing report.md test at this path
  (its fake turn no longer writes; positive control kept as the "existing file is kept" case).
- Reply over 1 MiB → file ≤ `MAXIMUM_ARTIFACT_BYTES`, ends with the truncation line, `read_artifact`
  serves it. *Mutation:* no truncation → `artifact_too_large`, red.
- Pre-existing `report.md` → unchanged bytes. *Mutation:* `open("w")` → bytes change, red.
- Block text: no "Write any file" and no `MEDIA:<path>` (update the assertion at
  `test_lens_exit_door.py` that pins `MEDIA:<path>`).
- **Live (the `RT-LENS-ARTIFACT-LIVE-PROOF` row):** an `investigate` monitor fires on a live serve; read
  (1) the receipt — `outcome: forged`, `tool_admission: read_only`, `files` = [`report.md`, size, sha256];
  (2) `runtime.lens.artifact {episode_id, name: report.md}` — content equals the agent's reply row in the
  Episode chat, sha256 equal; (3) the Launcher's Mission Control Lens receipts section — Open renders it
  (`EterniaLauncher/lib/features/mission_control/lens/mission_lens_receipts_section.dart`).

### Open questions

- **Owner decision (`RT-LENS-ARTIFACT-WRITE-TOOL`, non-blocking for this journey):** should an unattended
  read-only Lens turn get ONE narrow write — a `lens_write_artifact(name, content)` tool that writes only
  into the calling turn's Episode folder (folder bound from the turn, never from arguments), text types
  from `artifacts.ARTIFACT_TYPES` only, ≤ 1 MiB and ≤ 64 files — so it can leave a CSV or a data file
  beside the report? Options: (a) no — the reply report is the artifact; (b) yes, the scoped tool above,
  listed as mutating in `tool_visibility` but exempted from `read_only` for Lens chats only; (c) a
  per-monitor opt-in to (b). **Recommend (a)** until a journey needs a second file: (b) is the first
  exception to the 2026-10-22 read-only ruling, and the report needs none.
