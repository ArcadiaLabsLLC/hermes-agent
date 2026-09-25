# Layout sheet — `agent_runtime/agent_create.py` (lane R4)

Base: `main` @ `28012c8f8a` · sha256 `33a970791b01a0bfb38cfa64f1ec84d17a786ef42a08167accfe06ddd28ce2ca` · 2,126 raw / 1,439 code / 33 top-level defs · longest `perform_agent_create` 691 (1436–2126, depth 5 — the third-longest function left in the fork) · chains 0/0 · `str==` 2 · `isinstance` 11 · owner doc `docs/agent-runtime-harness/06-office-and-board.md` (the create sequence, UC-H1). 7 production importers (`persona_prewarm` ×7 names, `serve_rpc/agent.py` and `harness_parts/persona/lifecycle_commands.py` — the two lanes the docstring names — `snapshot/summaries`, `harness_parts/agent_commands`, `persona/chat_open`, `scripts/generate_agent_runtime_stream_fixtures`) taking 12 names; 14 test files pinning 8, one private (`_RESERVATION_ROLLED_BACK`).

**Package named after the file — `agent_runtime/agent_create/`** (siblings `agent_create_phases.py`, `agent_create_reservations.py` stay where they are and are imported by it). The file is one request's validation, one seven-phase sequence and the vocabulary both lanes answer in; the skeleton is exactly those three plus the phases the sequence writes.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300, hard cap 500; no flow over three modules)

```
agent_runtime/agent_create/
  __init__.py    wiring   the docstring (why the naming rule is load-bearing, UC-H1) + the map; re-exports the 12 importer names and _RESERVATION_ROLLED_BACK
  outcome.py     models   the VOCABULARY + errors module: ERR_* (re-spelled from serve_rpc, fenced), PHASE_*, PERSONA_*_REASON, _RESERVATION_ROLLED_BACK, AgentCreateInvalid, PersonaRosterUnavailable, AgentCreateSkillsRefused, AgentCreateRefusal, AgentCreateOutcome, refused, roster_unavailable_outcome, _skills_refusal (+ its sentence)  (~150)
  request.py     policy   AgentCreateRequest; the persona roster and its spellings (persona_roster, resolve_persona, accepted_persona_spellings, persona_not_found_message, _persona_is_unknown, require_known_persona, honest_default_display_name); mint_placement_id, _position, _skills, normalize_agent_create — "what is being asked, and is it well-formed"  (~400)   entry: normalize_agent_create, require_known_persona, resolve_persona, accepted_persona_spellings, honest_default_display_name, mint_placement_id
  phases.py      stores   the three durable phases and their read-back: placement_actor_payload, placement_slot_for, placement_position_policy; run_skills_phase, _inherited_skills_ack, _stamp_fresh_skills, _observed_skills; _live_actor, _reply; compensate_failed_placement  (~460)   entry: placement_slot_for, run_skills_phase
  perform.py     lanes    perform_agent_create — the ONE sequence (AgentCreate phases after the CHANGE)  (~400 in the MOVE, ~330 after)   entry: perform_agent_create
```

Per entry point, the modules an agent opens (the entry's module plus the modules of what it calls directly; a vocabulary/errors module is read like a table and not counted; the stores below — `persona_assignments`, `office_store`, `agent_create_reservations`, `agent_create_phases`, `skill_install`, `skill_resolution` — are named in §1.1's edges and not counted):

| entry point | opens | count |
|---|---|---|
| `perform_agent_create` (both lanes) | `perform` → `request` (normalize) → `phases` (mint/place/skills/reply/compensate) | 3 |
| `normalize_agent_create` / `require_known_persona` / the roster spellings | `request` | 1 |
| `run_skills_phase` (resume lane, `lifecycle_commands`) | `phases` → `request` (the skills spelling check) | 2 |
| `placement_slot_for` (`serve_rpc/agent.py`) | `phases` | 1 |
| `roster_unavailable_outcome` (`lifecycle_commands`, `persona_prewarm`) | `outcome` | 1 |

Two modules sit above the 300 target, and the ruling's three-module bound is why: the first draft split `request` into `request` + `persona` and `phases` into `placement` + `skills` + `reply`, which is cleaner by concept and made `perform_agent_create` — one request — open six modules. Refolded: `request` is one validation walk (syntax, then the roster, then the position, then the skills — in the order 582–588 insists on), and `phases` is the three writes one reservation covers, whose compensation has to see all three. Both are under the cap; neither is a god file by the gate.

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from imports) |
|---|---|---|---|
| 1–70 | docstring, imports (`.models` ×3, `.persona_assignments.{_display_name_for_template, _normalize_instance_source_persona, safe_assignment_text, safe_assignment_token}`) | `agent_create/__init__.py` | wiring |
| 77–92, 158–175, 225–234, 806–953, 959–971, 1399–1431 | `DEFAULT_AGENT_FOLDER` 77, `MAX_IDEMPOTENCY_KEY_LENGTH` 80, `AgentCreateInvalid` 83, `PersonaRosterUnavailable` 158, `PERSONA_NOT_FOUND_REASON` 225, `PERSONA_ROSTER_UNAVAILABLE_REASON` 234, `ERR_*` 816–819, `PHASE_*` 840–847, `_RESERVATION_ROLLED_BACK` 879, `AgentCreateRefusal` 887, `AgentCreateOutcome` 902, `_refused` 909, `roster_unavailable_outcome` 915, `AgentCreateSkillsRefused` 959, `_SKILLS_RETRY_SENTENCE` 1399, `_skills_refusal` 1405 | `agent_create/outcome.py` — imports `.models` only | models |
| 96–155, 178–221, 237–425, 428–682 | `AgentCreateRequest` 96 (+ lazy `persona_instance_id_for_placement`), `honest_default_display_name` 128, `persona_roster` 178 (lazy `.config`), `resolve_persona` 197, `persona_roster_unavailable_message` 237, `PERSONA_CHOICE_LIST_LIMIT` 257, `accepted_persona_spellings` 260, `_placeable_persona_choice_text` 295, `persona_not_found_message` 324, `_persona_is_unknown` 349, `require_known_persona` 390, `mint_placement_id` 428, `_position` 449, `MAX_SKILLS` 498, `_skills` 501, `normalize_agent_create` 550 | `agent_create/request.py` — imports `outcome`, `.models`, `.persona_assignments` (the two privates), `.config` (lazy) | policy |
| 685–804, 974–1392 | `placement_actor_payload` 685, `placement_slot_for` 730 (lazy `office_layout_policy`), `placement_position_policy` 771, `run_skills_phase` 974 (lazy `profile_home`, `persona_assignments`, `serde.safe_id`, `skill_install`, `skill_resolution`), `_inherited_skills_ack` 1144, `_stamp_fresh_skills` 1171, `_observed_skills` 1187, `_live_actor` 1236 (lazy `office_store`), `_reply` 1258 (lazy `office_models`), `compensate_failed_placement` 1360 | `agent_create/phases.py` — imports `outcome`, `request` | stores |
| 1436–2126 | `perform_agent_create` 1436 (lazy `time`, `call_authorization.service_backstop`, `agent_create_phases` ×4, `agent_create_reservations` ×6, `errors`, `office_class_key_guard`, `office_store`, `persona_assignments`, `persona_chat_durability`, `mission_chat_outcome.ChatErrorKind`, `gateway_announce`) | `agent_create/perform.py` — imports `outcome`, `request`, `phases` | lanes |

Edges point down: `perform` → `phases` → `request` → `outcome` → `.models`. The two private `persona_assignments` names (`_display_name_for_template`, `_normalize_instance_source_persona`) are imported from R1's package `__init__`, which re-exports them (persona_assignments sheet); this lane changes nothing there. No cycle: `serve_rpc/agent.py` and `lifecycle_commands.py` import DOWN into this package and nothing here imports either.

## 2. Routing sites → tables (the CHANGE commit)

W0-G5 holds no row for this file — its two ladders compare a NAME against CONSTANTS, which the gate's arm (a) cannot see. They are rule 12 all the same:

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| the resume ladder 1648–1796: `if record.state == STATE_DONE` / `STATE_PLACED` / `STATE_ROLLED_BACK` / `STATE_INSTANCE_MINTED`, each arm 10–70 lines, inside the 487-line `try` | four arms on one name, the reservation's state vocabulary (`agent_create_reservations.STATE_*`), each arm a whole resume behaviour | `perform.RESUME_ACTIONS: Mapping[str, Callable[[AgentCreate, record], AgentCreateOutcome \| None]]` keyed by the reservation state — `done → replay`, `placed → resume_skills`, `rolled_back → refuse`, `instance_minted → resume_placement`; an unknown state is the `reservation_corrupt` refusal the reservations module already spells (`test_agent_create_reservations.py::test_an_unknown_state_is_still_reservation_corrupt`) | swap the `done` and `placed` entries → `tests/agent_runtime/test_agent_create_service.py::test_an_idempotent_replay_re_reads_the_actor_instead_of_echoing_the_receipt` and `::test_a_resumed_placed_create_reports_the_actor_as_it_is` red |
| the placement fault cascade 1967–2028: `except ClassKeyedPlacementRefused` / `except (StaleRevision, SyncConflict, ValueError)` / `except Exception` | three hand-written translations of a store exception into `(code, reason, data, rolled_back)` — the serve_rpc sheet's `office_errors` class, one lane over | `phases.PLACEMENT_FAULTS: Mapping[type[BaseException], Callable[[exc], AgentCreateRefusal]]` walked by MRO; `perform` is `try: place() except BaseException as exc: return phases.refuse_placement(exc)`; the `ValueError` row keeps its own arm because it is the only one that stamps `PHASE_PLACEMENT` with `rolled_back: True` after a compensation | swap the `ClassKeyedPlacementRefused` and `StaleRevision` rows → `tests/agent_runtime/test_office_class_key_one_fence.py` reds (the class-key refusal answers `ERR_CONFLICT` where `ERR_INVALID_PARAMS` is asserted) |
| `PHASE_INSTANCE / PLACEMENT / SKILLS` 840–847, `PERSONA_NOT_FOUND_REASON` 225 and the `data.reason` strings | free `str` reasons and phases decoded by the launcher (`mission_agent_create_rpc.dart`, `MissionAgentCreateFault.phase`) | **not enum-ised** (batch-1 rule): `instance`/`placement`/`skills` are generic words, and the launcher's decoder — not a fork enum — is the fence the 831–847 comment names; `outcome.py` groups them as `PHASES: tuple[str, ...]` beside `refused`, their one writer | — (no conversion) |

W0-G7 floor rows (2):

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `perform_agent_create` 1436 | 691 / 5 | backstop FIRST, before normalize 1553 · normalize (eight refusals, `rolled_back: True` structurally) 1592–1611 · workspace gate, the emptiest refusal 1614–1638 · reserve 1641 · the resume ladder 1648–1796 · mint 1796– · place 1967–2028 · correlation/skills/announce 2066–2108 · reservation faults 2118 | `AgentCreate(request, stores).authorize → normalize → workspace_gate → reserve → resume_or_run → mint → place → skills → reply`, each ≤ 60, in `perform.py`; the subphase timers (`timed_create_subphase`) wrap the phase methods instead of blocks inside one function; `RESUME_ACTIONS` and `PLACEMENT_FAULTS` are the two tables it reads |
| `run_skills_phase` 974 | 168 / 3 | Gate 0 spelling 1023 · Gate 1 canonical ids installed and hash-equal 1042–1092 · Gate 2 every id resolves 1094 · the write (INSTANCE tier) 1113 · read BACK 1128 | `SkillsPhase.spelling → installed → resolved → write → read_back`, ≤ 45 each, in `phases.py`; the three gates are three methods named `gate_*` so the order the comments insist on is the method order |

`isinstance` 11 → ≤ 6 at review.

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_refused` 909 | `agent_retire._refused` 124, `persona_prewarm._refused` 216 — three 4-line bodies constructing three different outcome types | **NOT a fold** (three types); the name collision is retired here by `outcome.refused` (public); the other two are renamed when R2/R4 open their files — W0-G3's name arm counts private helpers only, so making this one public retires this file's share |
| `ERR_INVALID_PARAMS` … `ERR_CONFLICT` 816–819 | `serve_rpc/protocol.py`'s same-named constants | **NOT a fold, by the comment's own argument** (806–815): importing `serve_rpc` would drag the method registry into every CLI process and invert the edge (`serve_rpc/agent.py` imports THIS). The fence stays: `test_agent_create_service.py::test_the_services_error_codes_are_serve_rpcs_error_codes` |
| `_skills_refusal` 1405 / `_SKILLS_RETRY_SENTENCE` | none | `outcome` |
| `honest_default_display_name` 128 | the docstring's "ONE copy of that rule" | already the one owner; both lanes call it — unchanged |

## 4. Upstream doors

None. Every import is fork code; W0-G6 `private_upstream_imports` rows for this file: none. The `undeclared` row closes with the MOVE. No widening.

## 5. Dead code (verdict + the grep the lane runs)

No dead-code row names this file. `git grep -nw` over the 33 defs: every public name has an importer (§ header), every private one an in-file caller (`_inherited_skills_ack` 1144 ← 1131, `_stamp_fresh_skills` 1171 ← 1120, `_placeable_persona_choice_text` 295 ← 340). Nothing filed. The `runtime-queue.md` ghost-agent row (the placement-id discriminator this module refuses and `add_instance` accepts) is a DESIGN row, not dead code, and is not this lane's — the sheet keeps `mint_placement_id`/`looks_like_deliberate_placement` where they are and names the row.

## 6. Positive controls — land in the MOVE, before `RESUME_ACTIONS` (ruling Q6)

Three of the four resume arms are reached by name in `test_agent_create_service.py` (`test_a_replay_through_the_service_writes_nothing` → `done`; `test_a_resumed_placed_create_reports_the_actor_as_it_is` → `placed`; `test_a_replay_whose_instance_is_gone_returns_the_recorded_skills_unchanged` → `instance_minted`). The `rolled_back` arm (1719–1730) has no test spelling `STATE_ROLLED_BACK` (`git grep -n STATE_ROLLED_BACK tests/` → 0 today; the lane pastes the count). The MOVE lands a control: a receipt in `rolled_back` state replayed under the same key answers the recorded refusal and writes nothing. Then the table lands against a suite that reaches all four rows.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(agent_create): agent_create.py → agent_runtime/agent_create/ (4 modules; perform_agent_create whole)` — spans byte-identical with the sha256 table (one row per §1.1 span); `__init__` carries the docstring and re-exports the 12 importer names plus `_RESERVATION_ROLLED_BACK`. **Killing mutation for the MOVE:** drop `request` from `__init__`'s import list → `tests/agent_runtime/test_persona_prewarm.py` (imports `resolve_persona`) reds at import. The §6 control lands here. `[ds-size]` −1.
2. **CHANGE** `refactor(agent_create): AgentCreate phases + RESUME_ACTIONS + PLACEMENT_FAULTS; SkillsPhase gates; outcome.refused` — §2 + §3 with each red pasted; `[ds-size]` unchanged (already under after the MOVE).

## 8. Lane and what it must not touch

R4 (exec lane B2), third of its three, disjoint from the two gateway files. Must not edit in parallel: `agent_create_phases.py`, `agent_create_reservations.py` (consumed by name), `persona_assignments/` (R1's package — the two privates are read through its `__init__`), `office_store/` and `office_layout_policy.py` (R1/R3), `serve_rpc/agent.py` and `harness_parts/persona/lifecycle_commands.py` (the two lanes — retarget-only if a private name moves, and none does).
