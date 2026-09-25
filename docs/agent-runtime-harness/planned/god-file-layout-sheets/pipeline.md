# Layout sheet — `agent/charsheet/pipeline.py` (lane C1)

Base: `main` @ `28012c8f8a` · sha256 `74c1fd3b3e7f5738a895549efd5e7b9ba338a8dfac794c171929deb9aa8a32ea` · 2,533 raw / 1,898 code / 53 top-level defs · longest `detect_mirrored_art` 504 (1328–1831) · chains 0/0 · `str==` 10 · `isinstance` — · owner doc: the module docstring (plan H §4) and launcher ADR 0024 ruling 3-B. 3 production importers (`agent/charsheet/draft.py`, `agent/charsheet/fake_draftsman.py` — `MAGENTA` — and `hermes_cli/harness_parts/characters/steps.py`, all `from agent.charsheet import pipeline` and attribute access), 7 test files, all by module attribute.

**Fork-only file in an upstream directory** (program §0.3, ruling Q2): the new modules go under `agent/charsheet/`'s own package and nowhere else. `agent/charsheet/` is NOT under W0-G6's `LAYERED_ROOTS`, so the `__layer__` constants below are declared for the reader and for the day the roots widen; the gate cannot see them today, and the sheet says so rather than claiming a gate it does not have. The package's packaging boundary — "nothing here imports `agent_runtime`" (`agent/charsheet/__init__.py`) — is a rule this file already honours (its one runtime reach is `hermes_cli.config`, lazy); `draft.py` does not (its sheet, §4).

**Package is named after the file — `agent/charsheet/pipeline/`**, so `from agent.charsheet import pipeline` and every `pipeline.X` attribute the three importers and seven tests spell keep resolving through `__init__`. The `__all__` at 67–96 (30 names) is the public surface; the MOVE greps `pipeline\._[a-z]` across the 7 test files and re-exports each private name it finds, byte-for-byte the H3/H4 precedent.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300 code lines, hard cap 500)

This tree is the package `__init__` map, verbatim. Entry points are what the outside calls; everything else is reached only from inside the package.

```
agent/charsheet/_upstream_doors.py   models   the ONE place upstream pet/pixel names are imported (the 47–63 block as a module; a DOOR module, sub-100 by nature)
agent/charsheet/pipeline/
  __init__.py          wiring   the map; re-exports __all__ and the seven test-read privates
  geometry.py          models   chroma field, pixel budgets, prefixes, PNG/RGBA I/O                       (~110)
  provider.py          stores   the provider seam: deadline, _generate_image, _draftsman                   (~105)
  grounding.py         policy   cutout → magenta, cell framing, face offset, upscale/pad                   (~215)
  registration.py      policy   seam/registration arithmetic and the measured thresholds                  (~230)
  generate.py          lanes    turnaround, direction re-roll, row strips (reject-and-retry)              (~155)
  compose.py           lanes    palette + frame packing (the no-flip chokepoint) AND validate_sheet       (~320)
  handedness.py        lanes    detect_mirrored_art and the acceptance-basis tokens                      (~410 → ~300 after the CHANGE)
  handedness_report.py lanes    the operator-facing rendering of a finding                               (~325)
```

Per entry point, the modules an agent opens to follow it (the entry's own module plus the modules of what it calls directly; a callee that is itself an entry point is followed from its own row):

| entry point | opens | count |
|---|---|---|
| `generate_turnaround` / `generate_direction_view` / `generate_row_strip` | `generate` → `provider` → `grounding` | 3 |
| `frame_cell`, `face_offset`, `reference_cell` | `grounding` → `geometry` | 2 |
| `compose_sheet` / `compose_draft_frames` / `build_sheet_palette` | `compose` → `grounding` (+ `palette`, outside the package) | 2 |
| `validate_sheet` | `compose` → `handedness` → `handedness_report` | 3 |
| `detect_mirrored_art` | `handedness` → `registration` → `geometry` | 3 |
| `mirrored_art_error` / `handedness_summary` | `handedness_report` → `handedness` (tokens) | 2 |

Floor rule (ruling 3): `compose.py` absorbs `validate_sheet` because the 75-line compose half would be sub-100 and the file's own banner (884, "compose / validate") already names them one concept; no other module is under 100 except the door, which is exempt as a door/table module.

Layers point down: `geometry` ← `grounding`/`registration` ← `provider` ← `generate`/`compose`/`handedness` ← `handedness_report` ← `validate`. No module is drawn above 500; the one above 300 (`handedness.py`, for the MOVE only) comes under it in the CHANGE, which is why the detector's phases are the CHANGE's first row.

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from what it imports) |
|---|---|---|---|
| 1–96 | module docstring, imports, `logger`, `__all__` | `pipeline/__init__.py` (the map + re-exports) | wiring |
| 47–63 | the "ONE intentional drift surface": `imagegen`, `atlas.{CELL_HEIGHT, CELL_WIDTH, _clear_transparent_rgb, _fit_to_cell, extract_strip_frames, frame_x_bounds, normalize_cells, remove_background}`, `encoding.atlas_to_webp_bytes` | `agent/charsheet/_upstream_doors.py` (~40) — §4; the block's own comment already says it is a door | models |
| 98–284 | `MAGENTA` 102, `QA_BACKDROP` 115, `TRANSPARENT_BACKDROP` 122, `MAX_THUMB_PIXELS` 139, `MAX_CONSOLE_CARD_PIXELS` 179, `require_scale` 182, `fits_console_budget` 197, `fits_own_sheet` 212, `NON_DIRECTIONAL_VIEW` 244, `_ROW_GEN_ATTEMPTS` 247, `PREFIX_TURNAROUND` 251, `view_prefix` 254, `row_prefix` 259, `_open_rgba` 269, `_save_png` 279 | `pipeline/geometry.py` (~110) — imports `spec`, `palette` (for the `_open_rgba` fold, §3) and PIL lazily | models |
| 287–439 | `PROVIDER_TIMEOUT_SECONDS` 312, `provider_timeout_seconds` 315 (lazy `hermes_cli.config`), `_within_deadline` 340 (+ `_run`), `_generate_image` 379 (+ `_call`), `_draftsman` 421 (lazy `fake_draftsman`) | `pipeline/provider.py` (~105) — the ONE provider seam the docstring names | stores |
| 442–698 | `recomposite_on_magenta` 445, `frame_cell` 461, `FACE_BAND` 521, `_column_centroid` 524, `face_offset` 541, `reference_cell` 586, `upscale_on_backdrop` 602, `pad_to_square` 661 | `pipeline/grounding.py` (~215) — pure pixel work over `geometry` and the doors | policy |
| 701–881 | `turnaround_order` 701 (+ `rank`), `generate_turnaround` 730, `generate_direction_view` 785, `generate_row_strip` 816 (the geometric reject-and-retry, `_ROW_GEN_ATTEMPTS`) | `pipeline/generate.py` (~155) — imports `provider`, `grounding`, `prompts` | lanes |
| 884–972 | `build_sheet_palette` 887, `compose_draft_frames` 903, `compose_sheet` 947 | `pipeline/compose.py` — the chokepoint `agent/charsheet/__init__.py` names ("it has no flip in it") | lanes |
| 975–1325 | `MIRROR_GAIN_THRESHOLD` 1021, `REGISTRATION_WINDOW_DIVISOR` 1049, `registration_window` 1052, `_cell_distance` 1057, `_row_cells` 1071, `_padded` 1087, `_registered_distance` 1096, `_seam_distance` 1128, `_seam_record` 1163, `_seam_evidence` 1167, `_gain` 1179, `_contradicted` 1187, `_attribute_run` 1210, `_finding_from_run` 1264, `_run_findings` 1297 | `pipeline/registration.py` (~230) — the measured constants and the seam arithmetic; imports `geometry` and PIL only | policy |
| 1328–1831, 1842–1869 | `detect_mirrored_art` 1328 (+ `cells`, `blank`), `_ACCEPT_BASIS_TOKENS` 1842, `accept_basis_token` 1849, `_MIRROR_BASIS` 1862 | `pipeline/handedness.py` (~410 after §2's split; the function moves whole in the MOVE) | lanes |
| 1878–2247 | `_REROLL_IS_ONE_WAY` 1878, `_ACCEPT_IS_A_RECORD` 1890, `_block` 1897, `_disposition` 1921, `_corroborating_rows` 1932, `_accept_rows` 1959, `mirrored_art_error` 1998, `handedness_summary` 2202 | `pipeline/handedness_report.py` (~325) — the operator-facing rendering of a finding, apart from the detection | lanes |
| 2250–2533 | `_rgb_residue_count` 2250, `validate_sheet` 2269 | `pipeline/compose.py` (with the row above, ~320) — imports `handedness`, `handedness_report`, `registration`, `geometry` | lanes |

Result after the MOVE: 9 modules plus the door, none over 420. Edges, drawn (lazy included): `geometry` → `spec`, `palette` (down, same package); `provider` → `geometry`, `_upstream_doors`; `grounding`/`registration` → `geometry`, `_upstream_doors`; `generate` → `provider`, `grounding`, `prompts`; `compose` → `grounding`, `palette`, `_upstream_doors`, `handedness`, `handedness_report`; `handedness` → `registration`, `geometry`; `handedness_report` → `handedness` (the basis tokens). No cycle: `handedness_report` reads `handedness`'s tokens and `handedness` never reads a report. `draft.py` (its own sheet) keeps importing `pipeline` as a module, so the package's `__init__` is the only thing it sees.

## 2. Routing sites → tables (the CHANGE commit)

W0-G5 holds no ladder row for this file. What the CHANGE converts is rule 14's half — the finding dict's two free-string vocabularies — and W0-G7's three floor rows:

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `finding.get("severity") == "error"` at 1929, 2140, 2225, 2230, 2474, 2518; `entry["basis"] == "states"` / `"rotation"` / `"rotation and states"` at 1588, 1772, 1826; `finding.get("attribution") == "run"` 2069 | a `dict` finding with three free-string fields, compared by literal at nine sites across three functions | `handedness.Finding` (frozen dataclass: `rows`, `gain`, `basis: MirrorBasis`, `severity: Severity`, `attribution: Attribution`, `wholeState`, `alternatives`) with `MirrorBasis(StrEnum)` = today's `_MIRROR_BASIS` keys (1862–1869) and `Severity(StrEnum)` {error, warning}; the JSON payload `validate_sheet` returns is `Finding.as_payload()` so the wire is byte-identical. These words are NOT in the fork-wide vocabulary today (`scripts/god_file_probe.py::vocabulary` has no `states`/`rotation` member) — enum-ising them here is the first declaration, so the gate's arm (c) starts counting exactly these sites and no others | swap the `error`/`warning` members → `tests/agent/test_charsheet_pipeline.py::test_one_basis_warns_by_name_and_does_not_block_the_install` and `::test_a_warning_cannot_be_accepted_because_it_never_blocked` red |

W0-G7 floor rows (3; `CharacterDraft.compose` is the draft sheet's):

| row | lines / depth | phases (from the comment map) | after |
|---|---|---|---|
| `detect_mirrored_art` 1328 | 504 / 3 | states pass FIRST 1460–1463 (the rotation's attribution reads it) · rotation walk 1467–1585 · strict-majority conviction 1495–1550 · even-split refusal 1556 · per-state count 1573 · attribution 1741–1800 · summary 1802–1828 | `HandednessDetector(spec, cells)` with `states_pass() → rotation_pass() → convict() → attribute() → summary()`, each ≤ 90 lines, in `handedness.py`; the two closures `cells`/`blank` become methods; the ORDER (states before rotation) is already a test, not a comment — `tests/agent/test_charsheet_pipeline.py::test_a_lone_flagged_row_the_other_states_vouch_for_is_not_named` reds if `rotation_pass` runs first |
| `mirrored_art_error` 1998 | 202 / 1 | acceptance complaint 2055 · unattributed alternatives 2058–2095 · whole-state roster 2097–2138 · error rows 2140–2169 · the two trailing blocks 2171–2194 | `handedness_report.REPORT_SECTIONS: tuple[tuple[Callable[[Finding], bool], Callable[[Finding], list[tuple[str, str]]]], ...]` walked in order; `mirrored_art_error` becomes the walk plus `_block`; each section renderer ≤ 45 lines |
| `validate_sheet` 2269 (in `compose.py`) | 265 / 3 | size gate 2342 · boxes per row 2371–2407 · collapse/outlier walk 2409–2433 · residue 2436 · acceptances 2456–2506 · handedness 2509–2523 · payload 2525 | `SheetValidation.size_gate → boxes → outliers → residue → acceptances → handedness → payload`, ≤ 60 each; the "NOT conditional on the checks above" rule at 2439–2443 is pinned by `test_charsheet_pipeline.py::test_a_wrong_size_sheet_still_answers_the_handedness_question_honestly` |

`str==` 10 → 0 at review; every compare becomes a member compare.

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_open_rgba` 269 | `agent/charsheet/palette.py::_as_rgba` 52 — W0-G3 `body_groups[1]`, byte-identical bodies | FOLD: `palette.as_rgba` (made public; the name arm retires the underscore), `geometry` re-exports nothing — callers import `palette` |
| `_save_png` 279 | none in the fork | stays in `geometry` |
| `_within_deadline` 340 / `_generate_image` 379 | none | stay in `provider` |
| `provider_timeout_seconds` 315 reads `charsheet.provider_timeout_seconds` from `hermes_cli.config` | the config-key row already in `runtime-queue.md` (MOVE-A, 2026-09-24: the key's ruled home is the plugin manifest `config_schema`) | NOT a fold and not this lane's change — the reader stays; the row is the record |
| `_utc_now` ×3 (`draft.py` 350, `draft_lock.py` 95, `revisions.py` 74) | one body, three modules — the `clock.now_iso` class | NOT `agent_runtime.clock` (the packaging boundary); the draft sheet §3 creates `agent/charsheet/_fs.py` as the package's one owner of `utc_now` and the two atomic writers |

## 4. Upstream doors

`agent/charsheet/_upstream_doors.py` — one per fork package (ruling Q5); the 47–63 block IS the door today, spelled as a comment, and becomes a module: layer models, every name imported at CALL time as the doors module in `agent_runtime` does.

| reach | class | door |
|---|---|---|
| `agent.pet.generate.atlas._clear_transparent_rgb`, `._fit_to_cell` (module-level, 62) — `import_layers_grandfathered.json` `private_upstream_imports[0]`, `[1]` | NO (private) | `doors.clear_transparent_rgb(...)`, `doors.fit_to_cell(...)`; ruling Q7: door now, one **held widening row** per name in `upstream-footprint-ledger.md` (publish `fit_to_cell`, `clear_transparent_rgb`) |
| `atlas.{CELL_HEIGHT, CELL_WIDTH, extract_strip_frames, frame_x_bounds, normalize_cells, remove_background}`, `imagegen`, `agent.pet.generate.encoding.atlas_to_webp_bytes` | FIRST (public; `encoding.py` is fork-owned — not in `tests/fixtures/upstream_manifest.txt` — so not a door at all, and the sheet says so rather than counting it) | the same module, so the merge-break surface is one file |
| `hermes_cli.config.{cfg_get, load_config_readonly}` 327 (lazy) | FIRST (public) | through the door module; the queue row above owns the key's future |
| `PIL` | third-party | stays lazy at each site (the docstring's offline argument) |

No reach into `agent_runtime` — the boundary holds here.

## 5. Dead code (verdict + the grep the lane runs)

The five second-instalment rows (`dead-code-burn-down-queue.md`, lane C1) are all cold ARMS, not cold defs — and every one has a test that NAMES its case, which the reach census (0 hits each) contradicts:

| row | verdict | the test that names the arm |
|---|---|---|
| `detect_mirrored_art [if @1642]` (non-directional state → unjudged) | KEEP | `test_charsheet_pipeline.py::test_a_non_directional_state_is_reported_unjudged_with_its_reason` |
| `detect_mirrored_art [if @1705]` (both seams zero → unjudged) | KEEP | `::test_a_row_identical_to_both_neighbours_is_unjudged_not_dropped` |
| `mirrored_art_error [if @2058]` (unattributed alternatives) | KEEP | `::test_on_the_DEFAULT_two_state_sheet_a_run_is_never_attributed` |
| `mirrored_art_error [if @2097]` (whole-state roster) | KEEP | `::test_the_whole_state_message_names_the_state_and_the_override_it_accepts` |
| `validate_sheet [if @2342]` (wrong sheet size) | KEEP | `::test_a_wrong_size_image_fails_geometry_before_anything_else` |

The lane settles the contradiction before it closes a row: run the five named tests under the census's tracer (`downstream-god-file-refactor-reach-census.md`, its population and command) and paste the per-arm hit count. A hit closes the row KEEP-tested; a miss means the named test asserts the OUTPUT without reaching the ARM (a capture-is-a-vehicle case) and the lane writes the control in §6 before the CHANGE. `git grep -nw` over the 53 defs finds no def without an in-file or test caller; nothing new is filed.

## 6. Positive controls — land in the MOVE, before any table (ruling Q6)

For each §5 arm the tracer shows unreached: one fixture in `tests/agent/test_charsheet_pipeline.py` asserting the arm's OUTPUT (the `unjudged` row's `basis` and `reason`, the `alternatives` line, the roster line, the size error). The `REPORT_SECTIONS` killing mutation (swap the `wholeState` and `attributed` rows) is green by construction if 2058/2097 are unreached — that is why the controls come first.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(charsheet): pipeline.py → agent/charsheet/pipeline/ (9 modules) + _upstream_doors` — every span byte-identical: for each row of §1.1 the lander runs `git show 28012c8f8a:agent/charsheet/pipeline.py | sed -n a,bp | sha256sum` against the new module's span and pastes the table (11 rows — one per §1.1 span — plus the door block) into the commit body; `__init__` re-exports `__all__`'s 30 names plus the seven private names the tests read by attribute (`git grep -ho "pipeline\._[a-z_]*" tests` → `_column_centroid`, `_draftsman`, `_generate_image`, `_registered_distance`, `_row_cells`, `_run_findings`, `_seam_distance`); `_open_rgba` is NOT folded here (a fold changes bytes — CHANGE). **Killing mutation for the MOVE:** drop `provider` from `__init__`'s import list → the 15 `pipeline._generate_image` monkeypatches in `tests/agent/test_charsheet_pipeline.py` red on attribute lookup. The §6 controls, if any, land in this commit.
2. **CHANGE** `refactor(charsheet): Finding/MirrorBasis/Severity; HandednessDetector, REPORT_SECTIONS, SheetValidation phases; as_rgba fold` — §2 + §3 with each red pasted; the five §5 rows close; `[ds-size]` −1 (1,898 code → 0 over).

## 8. Lane and what it must not touch

C1, first of its two (this file before `draft.py`, which imports it as a module). In parallel it must not edit `agent/charsheet/{spec,palette,prompts,revisions,draft_lock,fake_draftsman}.py` beyond the one `as_rgba` rename in the CHANGE, nor `hermes_cli/harness_parts/characters/` (retarget-only, and only if a test there spells a private name); `agent/pet/` is upstream and is never edited — the two privates get ledger rows, not widenings here.
