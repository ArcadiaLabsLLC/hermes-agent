# Layout sheet — `agent_runtime/terminal_envelope.py` (lane R2 · exec lane 2B-B)

Base: `main` @ `28012c8f8a` · 1,262 raw / 963 code / 27 top-level defs · longest `envelope_decision` 141 (nine under the floor) · chains 0/0 · `str==` 0 · `isinstance` 3 · sha256 `ea8b97b119dddec8b434f88fa2d04795d3293870b9e1611bf3344ff1d7b9807a` · owner doc `docs/agent-runtime-harness/05-chat-turn.md` (the envelope). 13 production importers (`config`, `permission_modes`, `persona_chat_actor_prewarm`, `persona_chat_continuity`, `persona_runtime`, `process_notifications`, `profile_runner/{execute,models}`, `runtime_config`, `runtime_hud`, `terminal_envelope_explain`, `terminal_policy`), 11 test files. Importers take names from the `__all__` list (1213–1262, 49 names) — nothing private crosses the file; one test patches `explain_terminal_envelope`.

**Package `agent_runtime/terminal_envelope/`** (the sibling `terminal_envelope_explain.py` stays flat and keeps importing through `__init__`).

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/terminal_envelope/
  __init__.py   wiring  the map (the two-doors docstring, verbatim); __all__ verbatim (49 names)
  classes.py    models  VOCABULARY/TABLE module: the command-class taxonomy — the four classes, the legacy reason + summary tables, the pattern mirror, classify_command
  records.py    models  the typed records and their vocabulary: TerminalEnvelopeScope + the ContextVar ferry + scope_for_persona; the outcome / failure / grant-source / config-issue tokens; GrantIssue, Grants, Decision
  grants.py     policy  the ROOT-config grants table: role aliases, the config key, envelope_config, resolve_terminal_envelope_grants
  decision.py   policy  envelope_decision — the one answer per command; the fix hint, refusal_text, explain_terminal_envelope, hard_floor_command_classes
  receipts.py   stores  the audit root ladder and the two JSONL receipts; envelope_provenance, blocked_result (the tool-result shapes)
```
Entry points and the modules an agent opens: one terminal command on a governed lane (`tools/terminal_tool.py`, upstream) → `decision.py` → `grants.py` → `records.py` — **3** (+ `classes` for the classification), then `receipts.py` → `records.py` for the receipt — 2; `explain_terminal_envelope` (`runtime_hud`, `terminal_envelope_explain`) → `decision.py` → `grants.py` — 2; `scope_for_persona` (`profile_runner/execute`, `persona_runtime`) → `records.py` — 1; the config parse (`config._terminal_envelope_config`) writes what `grants.py` reads. Layers: `receipts` (stores) and `decision` (policy) → `grants` → `records`, `classes` (models); `grants.envelope_config` reaches `config` lazily (a flat sibling; lane 2B-C packages it — through `config/__init__`).

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–127 | docstring (the two-doors note), imports, `logger` | `__init__.py` (the docstring moves whole — it IS the module map's prose) | ~130 / 20 | wiring |
| 129–264 | `LANE_MISSION_CHAT`, `GOVERNED_LANES`, `GIT_PUSH` … `NETWORK_EGRESS`, `COMMAND_CLASSES`, `GRANTABLE_COMMAND_CLASSES`, `LEGACY_REASON_BY_CLASS`, `CLASS_SUMMARY`, `_NETWORK_ALLOWLIST`, `_CLASS_PATTERNS`, `_NETWORK_*_RE`, `classify_command`, `_network_class`, `legacy_reason_for_class` | `terminal_envelope/classes.py` (`re`) | ~140 / 100 | models |
| 267–460, 1135–1158 | `TerminalEnvelopeScope`, `_ENVELOPE_SCOPE`, `terminal_envelope_scope`, `current_terminal_envelope_scope`; `OUTCOME_*`, `ENVELOPE_COMMAND_*`, `GRANT_SOURCE_*`, `GRANT_*` issue codes, `TerminalEnvelopeGrantIssue`, `TerminalEnvelopeGrants`, `TerminalEnvelopeDecision`; `scope_for_persona` (lazy `personas.role_from_persona`) | `terminal_envelope/records.py` (`permission_modes`, `contextvars`, `dataclasses`) | ~220 / 150 | models |
| 463–613 | `_ROLE_ALIASES`, `canonical_role`, `grant_config_key`, `envelope_config`, `_lanes_for_role`, `resolve_terminal_envelope_grants` | `terminal_envelope/grants.py` (lazy `runtime_config`, `config`) | ~150 / 100 | policy |
| 616–812, 1161–1210 | `envelope_decision`, `_grant_fix_hint`, `refusal_text`, `explain_terminal_envelope`, `hard_floor_command_classes` | `terminal_envelope/decision.py` | ~250 / 170 | policy |
| 815–1132 | `ENVELOPE_DECISION_LOG`, `BLOCKED_ATTEMPT_LOG`, `AUDIT_ROOT_SOURCE_*`, `_audit_root`, `audit_root_source`, `_append_jsonl`, `record_envelope_decision`, `record_legacy_block`, `ENVELOPE_RESULT_KEY`, `envelope_provenance`, `blocked_result` | `terminal_envelope/receipts.py` (`paths.store_root` lazy, `json`, `os`, `time`) | ~320 / 180 | stores |

Refolded under the no-fragmentation ruling: the earlier draft's `scope.py` (~55 code) was under the floor; the scope is one of the typed records and lives with them in `records.py`. Result: 5 modules + the map, none over 180 code lines. Edges: all down; `decision` → `receipts` does not exist (the tool calls both); `receipts.blocked_result` → `decision.refusal_text` is stores → policy, DOWN. `runtime_hud` (lane 2B-B, lands before this) imports `ENVELOPE_DECISION_LOG` — from `__init__`. No lazy cycle.

## 2. Routing sites (rule 12)

| site (base line) | shape | verdict |
|---|---|---|
| `envelope_decision` 638–759 | five ordered arms over PREDICATES (ungoverned → ungated → config grant → mode grant → not grantable → requires grant) | guards, and the order is the argument (the docstring's three load-bearing properties) — stays a ladder of returns. The four `TerminalEnvelopeDecision(...)` constructions repeat six kwargs → `_decision(resolved, permission_mode, **kw)` builder takes the function from 141 to ~90 (the near-miss retires without a phase split) |
| `envelope_decision` 714–737 and `resolve_terminal_envelope_grants` 591–605 | the two hard-floor arms | **unreachable since ruling R-2**: `GRANTABLE_COMMAND_CLASSES = COMMAND_CLASSES` (171), so `name not in GRANTABLE_COMMAND_CLASSES` after `name not in COMMAND_CLASSES` can never hold, and `hard_floor_command_classes()` is always `frozenset()`. Dead-code queue row (line 63) names the second; the first is its twin. Owner question **Q20** (program doc §9): delete both arms + `hard_floor_command_classes` + the `GRANT_CLASS_NOT_GRANTABLE` issue, keeping `ENVELOPE_COMMAND_NOT_GRANTABLE` only if a reader pins it (1 test) — default: delete the arms, keep the two constants exported with a "no producer since R-2" note so the wire vocabulary a launcher may parse does not move |
| `_audit_root` 855–876 | three rungs (scope / env / resolver) | a fallback ladder over SOURCES, not a vocabulary; stays (`audit_root_source` names which rung answered — rule 14's shape) |

`str==` 0, `isinstance` 3 — nothing to lower.

## 3. Helper folds

| here | owner / duplicate | verdict |
|---|---|---|
| `_ROLE_ALIASES` 478 + `canonical_role` 483 | `config._RUNTIME_DEFAULT_PERSONA_ALIASES` 196, and the inline `keys` lists in `config.chat_lane_restore_toolsets` 518–522 and `config.mission_chat_workdir` 1013–1017 — the `alice_supervisor ⇄ neko_supervisor` alias spelled FOUR times, two-way in three of them and one-way here | recurrence (rule: the third instance files the CLASS): ONE owner **`personas.persona_id_aliases(persona_id) -> tuple[str, ...]`** (the role vocabulary's file) with the direction stated per caller; this lane folds `canonical_role` onto it, lane 2B-C folds the three `config` copies. Filed as a runtime-queue row in the report |
| `_append_jsonl` 889 | `chat_live_log._append_line`, `events.EventLog.append` — three JSONL appenders with three contracts (returns bool / rotates / is the log) | NOT a fold now; named as a `store_file_io.append_jsonl(path, row) -> bool` candidate once two contracts agree |
| `scope_for_persona`'s `role_from_persona` try/except 1147–1150 | `runtime_hud.capability_block_for_persona` 1310–1313 carries the same four lines | `personas.role_or_attr(persona)` — a 4-line owner; both fold (this lane owns both files) |

## 4. Doors

None imported. **The seam the file is waiting on**: `record_legacy_block`'s docstring (985–1027) carries the one-line delegation `tools/terminal_tool.py::_log_harness_blocked_attempt` should make; `tools/terminal_tool.py` is UPSTREAM (in `tests/fixtures/upstream_manifest.txt`) with a fork-added block, so that delegation is a fork edit inside an upstream file → a runtime-queue § Seams row if not already there (the lane greps the queue; files it if absent). No widening.

## 5. Dead code found while reading

| symbol | evidence | verdict |
|---|---|---|
| `TerminalEnvelopeDecision.explain` 443 | queue row (line 62): 0 hits; `git grep -n "\.explain()" -- '*.py'` over decision objects → nothing (`explain_terminal_envelope` is a different name) | DELETE in the MOVE with the tombstone row; the grep pasted |
| the two hard-floor arms + `hard_floor_command_classes` 1199 | §2 — unreachable by construction (`GRANTABLE == COMMAND_CLASSES`) | Q20; on the default: DELETE in the CHANGE, the queue row (line 63) closed |
| `audit_root_source`, `canonical_role`, `grant_config_key`, `envelope_config`, `CLASS_SUMMARY`, `LEGACY_REASON_BY_CLASS`, `AUDIT_ROOT_SOURCE_*` | 0 production importers by name; each read in-file | live |

## 6. Positive controls (ruling Q6)

1. Before `_decision(...)`: `test_terminal_envelope_grants.py` asserts a config grant carries `grant_source == "config_grant"` AND a mode grant carries `"permission_mode"` with `config_key is None` — both arms in one file (grep; add the missing one).
2. Before deleting the hard-floor arms: a test that temporarily narrows `GRANTABLE_COMMAND_CLASSES` (monkeypatch) and expects `ENVELOPE_COMMAND_NOT_GRANTABLE` would be the ONLY reader — if it exists, Q20 is answered "keep" by evidence and the sheet's default flips; the lane greps first.
3. `record_envelope_decision` returns `False` on a failed `_append_jsonl` (the 2026-08-09 detective-control claim): assert with an unwritable root; land if absent.

## 7. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(terminal_envelope): terminal_envelope.py → agent_runtime/terminal_envelope/ (5 modules); Decision.explain deleted` — spans byte-identical with one sha256 row per §1.1 range (`git show 28012c8f8a:agent_runtime/terminal_envelope.py | sed -n 'A,Bp' | sha256sum`); `__all__` verbatim; controls §6.1/6.3; `__layer__` per §1.
2. **CHANGE** `refactor(terminal_envelope): _decision builder; hard-floor arms retired (Q20); personas.persona_id_aliases + role_or_attr folds` — reds pasted; queue rows 62/63 closed; `[ds-size]` −1.

## 8. Lane and what it must not touch

Exec lane 2B-B, last. Must not edit in parallel: `terminal_envelope_explain.py`, `terminal_policy.py`, `profile_runner/` (batch 1), `persona_runtime.py`, `process_notifications.py` (importers through `__init__`); `config.py` — **lane 2B-C's file** (its three alias copies fold there, against the `personas` owner this lane creates — "tree wins" if 2B-C lands first); `tools/terminal_tool.py` (upstream; never).
