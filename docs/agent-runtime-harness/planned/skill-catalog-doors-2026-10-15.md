# Two upstream doors for the skill catalog walk (design)

Status: PLAN — written 2026-10-15; owner approval owed on WHICH doors to draft
(the owner already said yes to posting door drafts in one sitting, 2026-10-15;
no draft existed for this row). Row: runtime-queue, "Upstream
`tools/skills_tool._skill_catalog` parses every SKILL.md frontmatter itself,
and the kanban environment gate costs 3 ms per tagged skill uncached plus a
1.3 s first-call import".

## In plain English

When hermes lists the installed skills, upstream's code reads and parses every
skill file itself, even though the fork already keeps a cache of those parses;
and for skills tagged "kanban" it re-checks an environment setting on every
skill, with a very slow first check. The fork may not edit upstream files, so
the fix is to ask upstream for two small "doors" (hooks) and use them. This plan
says what the two doors are, how big the win is, and what to post.

## Evidence (tree at `origin/main` 428e2b0dd09)

- Catalog walk: `tools/skills_tool.py::_skill_catalog` (l.201) — on a cache
  miss, `_parse_frontmatter(_read_skill_text(skill_md)[:4000])` per file
  (l.226); the result is cached per session with a TTL and a scan signature
  (l.208–218), so the cost is paid per miss, not per turn.
- Measured: `9dc0b2ad19b` body — a primed cold child over the warm-budget seed
  (60 skills): `skills_tool.py` = 60 of 60 parses (the fork's own reads are 0,
  served by the parse cache `agent_runtime/parse_cache.py`, CF-1/CF-2); the
  kanban gate `agent/skill_utils.py::skill_matches_environment` → 
  `_detect_environment('kanban')` (l.151) costs 0.1 µs untagged, 3.0 ms per
  tagged skill (deliberately uncached: the verdict is context-dependent), and
  1,294 ms on the first call (imports of `tools.kanban_tools` /
  `hermes_cli.tools_config`).
- Related door already planned: `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md`
  § D1.10 S2 (`skill_view`'s result carries its frontmatter).

## The two doors

1. **Frontmatter reader hook.** `agent/skill_utils.py` gains
   `set_frontmatter_reader(fn)` (default: today's read+parse); `_skill_catalog`
   and `skill_view` call it. The fork registers its parse cache (keyed on path,
   mtime, size) at plugin load. Additive: no behaviour change without a
   registered reader. Folds in D1.10 S2 (one door, not two).
2. **Per-walk environment memo.** `_skill_catalog` evaluates
   `_detect_environment(tag)` once per tag per walk (a dict local to the walk),
   so 3 ms × N tagged skills becomes 3 ms × distinct tags. Context-correct:
   the memo lives only for one walk in one context, which is the property the
   process cache lacked. The 1.3 s first import is a separate ask: import the
   kanban detector lazily only when a skill carries the tag (it already does —
   the cost is the import itself; leave it, record it).

## Owner decisions (recommendation first)

1. **Draft both doors** (recommended): door 1 also serves D1.10, door 2 is a
   pure upstream speed-up with no fork carry.
2. **Is the win worth a PR at all?** The catalog is cached per session, so the
   win lands on cold processes (serve boot, CLI one-shots, the bundled first
   turn) — the budget gate in `test_stream_relay.py` measures exactly that.
   Recommend yes for door 1 (removes a named residue in a measured gate), and
   door 2 only if a persona carries several kanban-tagged skills (S0 counts).
3. **Posting** follows the upstream contribution rules (CONTRIBUTING + issue
   template first); the owner posts (nekwo cannot open PRs).

## Slices (build order)

- **S0 — count:** kanban-tagged skills in the bundled and shared skill roots;
  cold-child parse and gate time with the current tree (re-run the
  `9dc0b2ad19b` measurement). Record in this doc.
- **S1 — draft door 1** on an upstream-based branch: hook + tests in upstream's
  style. Killing mutation: `_skill_catalog` bypasses the hook → the upstream
  test with a counting reader sees 0 calls → red.
- **S2 — draft door 2** (if S0 says so). Killing mutation: memo keyed
  process-wide → a test with two contexts disagreeing on kanban leaks the first
  verdict → red.
- **S3 — fork consumer** (after merge): register the parse-cache reader; the
  cold-child gate's `skills_tool.py` parse count drops from 60 to 0. Killing
  mutation: unregister → the gate's count assertion reds.

## Blast radius

Upstream drafts only until merged; then one registration line in the fork
plugin and a tightened count in `test_stream_relay.py`. Footprint ledger rows
filed as held PR rows.

## What it retires

The last unattributed frontmatter parse in the cold-start budget, D1.10 S2 as a
separate door, and the per-skill kanban re-check.
