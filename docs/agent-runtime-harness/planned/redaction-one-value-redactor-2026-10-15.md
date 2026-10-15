# One value redactor for every lane; the secret word lists go (design)

Status: PLAN — written 2026-10-15; owner approval owed. Row: runtime-queue,
"Word-based redaction, the CLASS (third instance)".

## In plain English

When the runtime shows the operator what an agent did, it hides secrets. Some
places do it well: they find the secret **value** (`API_KEY=abc123…`) and blank
just that. Other places still use the old way: if a line contains a scary
**word** like "token" or "password", the whole line or field disappears — so a
file called `token_budget.py`, or a thought that mentions "the password field",
vanishes, while a secret with no scary word next to it can slip through. L2.21
fixed four lanes; about thirty sites remain. This plan moves every remaining
lane onto the one value redactor and deletes the word lists.

## Evidence (tree at `origin/main` 428e2b0dd09)

- The one value redactor: `agent_runtime/redaction.py::scrub_secret_values`
  (l.393) and `scrub_secret_value_tree` (l.402).
- Word lists still deciding (41 references across 6 files):
  `progress.py` (17: `_looks_sensitive` l.791, `_looks_sensitive_or_pathish`
  l.778), `profile_runner/dispatch_payloads.py` (7),
  `profile_runner/operator_redaction.py` (6: `_OPERATOR_SECRET_MARKERS` l.53,
  `_line_has_secret` l.97), `observability.py` (6:
  `_looks_sensitive_or_pathish` l.444), `events.py` (3: its own copy l.792),
  `profile_runner/tool_payloads.py` (2).
- **Three copies** of `_looks_sensitive_or_pathish` (events, observability,
  progress) that differ in their marker lists — duplicate authority.
- Precedent and test pattern: `a325b7c08e` (L2.21, command/output/target/path
  lanes) and `tests/agent_runtime/test_tool_io_value_redaction.py`; observe
  mode `tests/agent_runtime/test_redaction_observe.py`
  (`HERMES_REDACTION_MODE=observe` keeps payloads with a `would_redact` marker).

## Target shape

- **Secrets:** every lane calls `scrub_secret_values` /
  `scrub_secret_value_tree`. No lane withholds a field because of a word.
- **Paths are a separate policy, not a secret test.** The "pathish" half
  (absolute paths, `~`, drive letters) becomes one function,
  `redaction.mask_local_paths(text, *, roots)`, that shortens a path to a
  root-relative label instead of dropping the field. One copy, used by the
  three modules that have their own today.
- **Observe mode unchanged in kind:** `would_redact` records what the value
  redactor replaced; hard-fail stays on for the transport fold.
- Word lists deleted; a negative gate forbids reintroducing a marker tuple
  used as a decision.

## Owner decisions (recommendation first)

1. **Paths: shorten (recommended) or keep hiding fields that look like paths.**
   Hiding whole fields for a slash was the same over-blanking defect; a
   root-relative label keeps the operator's context and leaks no home path.
2. **Unknown-key fields in progress payloads** (`unsupported_progress_key`):
   recommend keep the allow-list of keys (that is a SHAPE rule, not a word
   rule) and value-scrub what passes it.
3. **One lane or per-module lanes.** Recommend one lane, one commit per module,
   because the corpus and the gates are shared and the security review is one.

## Slices (build order)

- **S0 — corpus.** Extend `test_tool_io_value_redaction.py` with a table:
  (a) secret value with no marker word → must be blanked; (b) marker word with
  no secret value (`token_budget.py`, "the password field") → must survive;
  (c) secret value beside a marker word → value blanked, rest kept. Run it red
  against today's lanes and record which rows fail where.
- **S1 — `progress.py`** onto the value redactor. Killing mutation: restore
  `_looks_sensitive` as the gate → corpus row (b) reds.
- **S2 — `dispatch_payloads.py` + `operator_redaction.py`**; delete
  `_OPERATOR_SECRET_MARKERS` / `_line_has_secret`. Killing mutation: skip the
  value redactor on the dispatch reasoning field → corpus row (a) reds.
- **S3 — the path policy:** one `mask_local_paths`; the three
  `_looks_sensitive_or_pathish` copies deleted. Killing mutation: let an
  absolute home path through → a path-leak test reds.
- **S4 — `tool_payloads.py`, `events.py`, `observability.py`** remaining sites.
- **S5 — negative gate** `tests/tooling/test_no_secret_word_decisions.py`: a
  source walk refusing a tuple of marker words consumed by `any(... in lowered)`
  in fork modules. Killing mutation: re-add one → red.

Each slice runs the redaction corpus, `test_redaction_observe.py` and the
stream goldens (bytes may change only where the corpus says they should;
regenerate and diff-review).

## Blast radius

Six fork modules on the security path, their tests, the stream goldens, one
new gate. Launcher sees more (correct) text in progress/dispatch rows; no wire
field changes name.

## What it retires

Word-list redaction (third and last instance of the class), three duplicate
"sensitive or pathish" policies, and over-blanking of ordinary operator text.
