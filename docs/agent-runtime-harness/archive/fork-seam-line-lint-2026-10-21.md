**BUILT — archived 2026-10-27 by triage lane w1027j-h-tri-a; landing commits 70aa5b8cd7, 81d12a3380, 3e6a0e1048.**
F1–F3 landed.

# Planned — `scripts/check` with a fork scope: upstream's own lines never red the local gate — 2026-10-21

**Owner domain:** the repository as a fork (`docs/downstream-development.md` § The fork landing gate;
`scripts/check`, `scripts/check-windows-footguns.py`, `scripts/upstream_footprint.py`;
[Merging upstream](../../../Harness_Brain/50%20—%20Agent%20Handoffs/Merging%20upstream.md)).
**Status:** IMPLEMENTATION-READY (design lane w1021i-plans). One doc, no code. Lane w1021i-hygiene is
fixing the lines on `w1021i/hygiene` now; this plans only what remains after it lands.
**Measured / read:** 2026-10-21 against hermes `origin/main` d087df7035 and `origin/w1021i/hygiene`
28f654079a.

Row: `FORK-SEAM-LINE-LINT` (fork-hygiene-queue).

## 1. What is true today — measured

`python scripts/check --only footguns,no-tmp,ruff` on `origin/main` (ruff 0.15.10 through the test venv;
`scripts/check` resolves none on a bare PATH — `uvx ruff@0.15.10` is the documented fallback): **FAILED
footguns, ruff; no-tmp green.** 19 ruff reds (12 `RUF100` unused-noqa, 7 `UP006` typing aliases) in
16 files + 2 footguns (`hermes_cli/config.py:2579` and `:2633`, bare `read_text`/`write_text`), every
one on a fork-added line inside an upstream file (the `# fork …` / `# noqa … — fork` comments say so):
`agent/session_persistence.py`, `hermes_cli/{config,gateway,gateway_windows,version_info,
web_server_oauth}.py`, `pm/plugins_state.py`, `tools/{skills_tool,terminal_tool,tool_search}.py`,
`tui_gateway/{server,contracts/__init__}.py`, three fork tests.

`origin/w1021i/hygiene` (28f654079a, "clear main's ruff and Windows-footgun reds on fork-added lines")
touches exactly those 16 files (+ the merging-upstream handoff): 29 insertions, 26 deletions, rewrites
only. So the LINE half of the row is that lane's; nothing here re-plans it. Its landing must show the
footprint unchanged (`scripts/upstream_footprint.py` 230/1035/1 — the same lines, re-spelled).

What remains is the STRUCTURAL half: `scripts/check::_jobs` runs ruff over `.` and footguns with
`--all`, with no fork scope. The next release merge brings upstream's own new lines under the fork's
stricter ruff selection (the fork enables `RUF100`/`UP006` where upstream does not) and the footgun
scanner, and the local gate reds on lines the fork may not edit (upstream files are additive or not at
all). That is the recurrence the row is about.

## 2. Decisions

- `Decided (plan):` **the gate judges fork lines only.** A red on an upstream-owned line is reported as
  `upstream (not judged)` and never fails the check; a red on a fork-added line, or in a fork-owned file,
  fails as today. "Fork-added" is a LINE fact: the line is absent from the file's blob at the upstream
  merge base — the same classification `scripts/upstream_footprint.py` already computes per file
  (fork-owned / seam / upstream-owned) extended to lines by `git diff <base>...HEAD --unified=0` per seam
  file. The base is the last release merge's upstream parent (`Merging upstream.md`'s "daily base"
  rule, 0077088f8e), read from `git merge-base upstream/main HEAD` when the ref exists, else from the
  footprint ledger's recorded tag.
- `Decided (plan):` **no `--fork-scope` flag, no second mode.** The scope is the gate's one behaviour
  locally and in CI (`ci/main` runs the same script); an upstream red is still PRINTED (count + first
  five locations) so a merge lane sees what upstream brought, and `--judge-all` exists for the merge lane
  that wants the old whole-tree verdict.
- `Decided (plan):` **footguns and ruff share the one line filter.** `scripts/check` post-filters each
  tool's output (`ruff check --output-format json`; the footgun scanner already prints `path:line`)
  through `scripts/code_health/fork_lines.py::is_fork_line(path, line_no)`; the tools themselves are not
  changed (ruff's own `--diff`/`--extend-exclude` cannot express "lines not in a base blob").

## 3. Stages

**F1 — `scripts/code_health/fork_lines.py`**: `ForkLines.load(root, base_ref) -> ForkLines` builds, once
per run, `{path: FORK_OWNED | set[int]}` — fork-owned files (not in `upstream/main` at the base, via the
footprint's rule) map to the sentinel; seam files map to the set of added line numbers from `git diff
--unified=0 <base> HEAD -- <path>` (`+` hunks only); upstream-owned files map to the empty set.
`is_fork_line(path, line)`; `summary()` for the receipt. Tests (`tests/scripts/test_fork_lines.py`, a
fixture repo with a fake `upstream` base commit): a line added after the base is a fork line; a line
present at the base is not; a file absent at the base is wholly fork; a renamed-only hunk (` ` context)
is not. Killing mutation: read `-` hunks too → the "present at base" test reds.

**F2 — the filter in `scripts/check`**: ruff runs with `--output-format json` under the gate and the
script renders one format itself — `path:line:col CODE message` for judged reds, then `upstream (not
judged): N` with the first five locations — whether or not a terminal is attached. Footguns likewise
(`check-windows-footguns.py --all --json` — a 10-line additive flag on that scanner, which is
fork-owned). `--judge-all` bypasses the filter. Tests (`tests/scripts/test_check_fork_scope.py`, the
same fixture repo, a planted `Dict[str, Any]` on an upstream base line and one on a fork-added line):
the gate fails naming only the fork line; `--judge-all` fails naming both; the upstream count is 1.
Killing mutation: treat every seam file as wholly fork → the "only the fork line" test reds (both
named).

**F3 — the receipt and the docs:** `docs/downstream-development.md` § The fork landing gate gains the
scope sentence and `--judge-all`; `Merging upstream.md` step 7 runs `--judge-all` once and files
upstream's own reds as a `FORK-UPSTREAM-LINT-<tag>` row (marker only, never an edit — the § Upstream-owned
rule), so a release merge's reds are a filed fact and never a green bought by the filter in silence.

## 4. Out of scope

The lines themselves (lane w1021i-hygiene); ruff's rule selection (`pyproject` dev group); CI's runner
queue and `FH-CI-MAIN-LINT-REDS` (that row closes when the hygiene lane lands; this plan prevents its
recurrence).

## 5. Open rulings

None. (If the hygiene lane's landing leaves any red that is NOT on a fork-added line, it is an upstream
red and goes to a `FORK-UPSTREAM-LINT-v0.22.2` marker row under § Upstream-owned, not to this plan.)
