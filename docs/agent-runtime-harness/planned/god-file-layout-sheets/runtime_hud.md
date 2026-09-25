# Layout sheet — `agent_runtime/runtime_hud.py` (lane R2 · exec lane 2B-B)

Base: `main` @ `28012c8f8a` · 1,437 raw / 1,103 code / 37 top-level defs · longest `render_situational_hud_block` 146 (four lines under the floor) · chains 3/0 · `str==` 6 · `isinstance` 34 · sha256 `55ffa9d51f6a25fb077beed33765b13a7e9719231156459e744ed96ae9ba4537` · owner doc `docs/agent-runtime-harness/05-chat-turn.md` (the HUD) and `07-observability.md`. 5 production importers (`mission_chat_turn_context`, `persona_chat_continuity`, `chat_lane_bundle`, `persona_chat_history/curation`, `prompt_observability/snapshot_frame` — which lazily imports the PRIVATE `_installs_block`), 16 test files (two import `_mission_chat_surface_message`/`_mission_chat_user_message` FROM `persona_runtime`, not from here). Importers take `resolve_situational_hud`, `situational_hud_for_instance`, `capability_block_for_persona`, the two `extract_*_envelope`, `situational_hud_revision`, `render_*`, `skill_preload_*`, the `*_CODEC`s.

**Package `agent_runtime/runtime_hud/`.**

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/runtime_hud/
  __init__.py     wiring  the map; re-exports the importer names + installs_block (public spelling of _installs_block)
  fields.py       models  VOCABULARY/TABLE module: HudField / HUD_FIELDS — the ONE declaration of which lane a key rides; stable_hud_fields; the revision hash; the two caps
  envelopes.py    policy  the two envelope grammars (runtime_context, skill_preload): extract / render / delivery choice / revision / split / EnvelopeCodec
  hud.py          policy  the HUD itself: resolve_situational_hud and its block builders (lane, mission, roster, residency stamp, steering) and render_situational_hud_block — the hashed body's prose — with the handle / install / age phrasings
  capability.py   policy  resolve_capability_block + render_capability_block — the volatile tail's capability account
  ambient.py      lanes   the chat-side wrappers that do I/O: situational_hud_for_instance, capability_block_for_persona, the board digest, installs_block
```
Entry points and the modules an agent opens: the chat turn's HUD (`mission_chat_turn_context`) → `ambient.py` → `hud.py` → `fields.py` — **3**; the observability frame (`prompt_observability/snapshot_frame`) → `hud.resolve_situational_hud` + `ambient.installs_block` — 2; the capability account → `ambient.py` → `capability.py` — 2; the envelope round-trip (`persona_chat_history/curation`, `persona_runtime`) → `envelopes.py` — 1. Layers: `ambient` (lanes) → `hud`, `capability`, `envelopes` (policy) → `fields` (models); `capability` imports `terminal_envelope.ENVELOPE_DECISION_LOG` and `chat_lane_toolsets.DROP_KIND_*` (flat siblings), nothing above policy.

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–61 | docstring, imports | `__init__.py` | ~70 / 20 | wiring |
| 64–71, 110–235 | `SITUATIONAL_HUD_ROSTER_CAP`, `SITUATIONAL_HUD_CAPABILITY_CAP`, `CAPABILITY_HUD_KEY`, `HudField`, `HUD_FIELDS`, `_HUD_FIELD_BY_KEY`, `hud_field`, `is_volatile_hud_key`, `volatile_hud_keys`, `stable_hud_fields`, `situational_hud_revision` | `runtime_hud/fields.py` (`hashlib`, `json`) | ~140 / 100 | models |
| 73–107, 238–525 | `RUNTIME_CONTEXT_DELIVERY_*`, `_RUNTIME_CONTEXT_ENVELOPE_RE`, `SKILL_PRELOAD_DELIVERY_*`, `_SKILL_PRELOAD_ENVELOPE_RE`, `_SKILL_PRELOAD_NAME_RE`, `extract_runtime_context_envelope`, `runtime_context_delivery`, `render_runtime_context_envelope`, `skill_preload_revision`, `skill_preload_delivery`, `render_skill_preload_envelope`, `extract_skill_preload_envelope`, `ComposedUserRow`, `split_composed_user_row`, `EnvelopeCodec`, `SKILL_PRELOAD_CODEC`, `RUNTIME_CONTEXT_CODEC` | `runtime_hud/envelopes.py` (`re`, `hashlib`) | ~320 / 200 | policy |
| 528–590, 613–1024 | `_clean`, `_lane_block`, `_mission_block`, `_thread_count`, `_roster_block`, `_stamp_residency`, `_parent_refs`, `_resolve_parent_ref`, `_steering_block`, `resolve_situational_hud`, `render_situational_hud_block` (+ nested `_handle`), `_install_summary`, `_age_phrase` | `runtime_hud/hud.py` (`serde.optional_text`, `models.looks_like_persona_instance_id`) | ~470 / 300 | policy |
| 1027–1246 | `_capped`, `_names`, `resolve_capability_block`, `render_capability_block` | `runtime_hud/capability.py` (`chat_lane_toolsets`, `permission_modes`, `terminal_envelope`) | ~220 / 150 | policy |
| 593–610, 1249–1437 | `_installs_block` (→ public `installs_block`), `capability_block_for_persona`, `_board_digest_for_workspace`, `situational_hud_for_instance` | `runtime_hud/ambient.py` — lazy reaches `persona_assignments`, `store`, `workspace_scope`, `board_store`, `persona_runtime`, `tool_permissions`, `personas`, `terminal_envelope`, `gateway_targets`, `peer_directory` | ~210 / 130 | lanes |

Refolded under the no-fragmentation ruling: the earlier draft split `resolve.py` (~180 code) and `render.py` (~140) — one HUD, read then rendered, is one module (`hud.py`, at the 300 target's edge; it is the one module the CHANGE may split again if the `_handle` lift and the `_section` idiom do not bring it under). Result: 5 modules + the map. Edges: all down. The lazy cycle `persona_runtime` ↔ `runtime_hud` (`capability_block_for_persona` → `chat_lane_capability_drops`; `persona_runtime` → this package) stays lazy on both sides and lives in `ambient.py` only — no policy module may name `persona_runtime`.

## 2. Routing sites (rule 12)

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `resolve_capability_block` 1100–1105 | three arms on `drop.kind` (`== DROP_KIND_TOOLSET` / `== DROP_KIND_TOOL` / else skip) — **invisible to W0-G5 (a)/(c)**: compares against NAMES bound to strings (the probe counts `chains 3/0`); the class is filed in the report | `_DROP_BUCKETS: Mapping[str, str] = {DROP_KIND_TOOLSET: "toolsets_dropped", DROP_KIND_TOOL: "tools_dropped"}`; an unlisted kind is skipped by the `.get` miss | swap the two bucket names → `tests/agent_runtime/test_runtime_hud_capability_visibility.py` reds — after control §6.1 confirms it asserts BOTH buckets |
| `render_situational_hud_block` 881–885 | the board segments | already a table |
| `_age_phrase` 1018–1024 | four thresholds on seconds | a numeric ladder, not a vocabulary — allowed; optional `_AGE_UNITS` table in the CHANGE, not required |
| `render_runtime_context_envelope` 301–314, `render_skill_preload_envelope` 396–403 | delivery arms (`snapshot`/`unchanged`/else) | validate-then-render boundaries; stay. The delivery words are spelled in the envelope grammar (the regex) and in `persona_chat_history` — no Enum (fork-hygiene row, lane R4) |

`isinstance` 34 → ≤ 25 at review (the `hud.get(...) if isinstance(...) else {}` idiom becomes `_section(hud, key)` in `hud.py`).

## 3. W0-G7 near-misses (no fixture row; two functions one edit from GREW)

| row | lines | after |
|---|---|---|
| `render_situational_hud_block` 832 | 146 (+ the 26-line nested `_handle` closure reading `_age_phrase`) | lift `_handle` to `_render_handle(entry)` at module level → the function drops to ~115 and the closure stops reading enclosing scope |
| `resolve_situational_hud` 724 | 106 | fine; the docstring is half of it |

## 4. Helper folds

| here | owner | verdict |
|---|---|---|
| `_age_phrase`'s parse 1011–1016 | `store.ledger_time` (the tolerant ISO → aware-UTC datetime owner; `realm_sync` already folded onto it) | the body belongs in `clock` (a leaf), not in `store` (a stores package a policy module may not import): **`clock.parse_iso_utc(value) -> datetime \| None`** — created by whichever of lane 2B-A (`store`) and this lane lands first ("tree wins"); `ledger_time` becomes its alias, `_age_phrase` calls it. Behaviour-identical for `_age_phrase` (Python 3.11 `fromisoformat` already accepts `Z`) |
| `_capped` 1027 | `serde.dedupe_tokens` (no cap, token-normalizing) | NOT a fold — this keeps free text and counts the overflow. Named |
| `_clean` 528 | `serde.optional_text`'s truthiness | stays (a 1-line predicate) |
| `hud_field` 178, `volatile_hud_keys` 198 | dead-code queue row (line 22): 0 production, 2 tests each | TEST SEAM per the FORK-CODE verdict: the two tests read `HUD_FIELDS` directly; both accessors deleted in the MOVE, row deleted |

## 5. Doors

None: `hashlib`, `json`, `re`; every import is fork. W0-G6 private rows: none. `prompt_observability/snapshot_frame.py:99` imports the private `_installs_block` — made public as `installs_block` in the MOVE (the importer is a batch-1 package; a one-line retarget the sheet allows).

## 6. Positive controls (ruling Q6)

1. Before `_DROP_BUCKETS`: `test_runtime_hud_capability_visibility.py` must hold one drop of each kind in ONE block and assert both `toolsets_dropped` and `tools_dropped`; if it asserts only one, add the other (the swap mutation is green against a single-bucket fixture — capture-is-a-vehicle).
2. The seam `setattr(runtime_hud, "capability_block_for_persona", …)` retargets to the module the CALLER reads (`mission_chat_turn_context` imports it lazily by attribute → the package attribute still works; verify by reverting the retarget and watching the test).
3. `_stamp_residency`: assert a roster entry whose handle appears in a cached far roster gains `also_on` and one whose display NAME matches does not (the docstring's claim, pinned).

## 7. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(runtime_hud): runtime_hud.py → agent_runtime/runtime_hud/ (5 modules); installs_block public; hud_field/volatile_hud_keys to the test seam` — spans byte-identical with one sha256 row per §1.1 range (`git show 28012c8f8a:agent_runtime/runtime_hud.py | sed -n 'A,Bp' | sha256sum`); `__init__` re-exports; controls §6; `__layer__` per §1.
2. **CHANGE** `refactor(runtime_hud): _DROP_BUCKETS; _render_handle lifted; _section idiom; clock.parse_iso_utc` — reds pasted; `[ds-size]` −1.

## 8. Lane and what it must not touch

Exec lane 2B-B, second (after `mission_chat_turns`; before `terminal_envelope`, whose `ENVELOPE_DECISION_LOG`/`LANE_MISSION_CHAT`/`explain_terminal_envelope` this package keeps importing through `terminal_envelope/__init__` once that lands). Must not edit in parallel: `persona_runtime.py`, `mission_chat_turn_context.py`, `chat_lane_bundle.py`, `persona_chat_continuity.py` (importers through `__init__`); `prompt_observability/`, `persona_chat_history/` (batch-1 packages — the one-line `installs_block` retarget only).
