> **BUILT** — archived 2026-10-27 from `planned/` (lane w1027j-h-tri-b); landed: lines 1-2 `4337842853`, line 5 `4cb63e5b19`; lines 3, 4, 6 and 8 ruled not seeded (`e878442cf2`).
> History, not truth: the domain docs and the queues hold what is current.

# Default seed values for the door-fit PARTIAL keys on persona create (draft for owner approval)

Status: DRAFT VALUES — written 2026-10-15 for the owner to approve, per the
2026-10-10 ruling ("orchestrator drafts default seed values from
door-fit-2026-09-27.md for the owner to approve"); no seed lands before
approval. Row: runtime-queue, "Seed the door-fit PARTIAL keys … on persona
create — HERMES seeds them, not the launcher" (owner, 2026-10-03).

## Build status (lane h4-seeds, 2026-10-16)

- **S0 — the writer.** No fork code writes a new profile's `config.yaml`: upstream
  `hermes_cli/profiles.py::create_profile` does, behind three upstream-owned callers (CLI
  `profile create`, REST `POST /api/profiles`, ws `profiles.create`). The fork's
  persona-create door is `agent_runtime/persona_profiles.py::promote_profile_to_persona`.
  So the one writer is `agent_runtime/persona_seed_defaults.py`, called from that door
  (at mint) and from the plugin's startup sweep (every persisted persona's bound profile,
  which is what reaches a profile upstream created).
- **S1 + S2 — built for lines 1 and 2** (fill-if-absent, round-trip writer, fail-open).
- **Held, with the question each needs:**
  - Line 3 — **RULED 2026-10-21 (owner): not seeded.** Creates stay profile-local and
    promote through the hash-guarded door (`agent_runtime/skill_promotion.py`).
  - Line 4 — sequencing, and a question (lane w1021h-cli, 2026-10-21): the shared root is
    already a search root through the fork's tier in
    `agent/skill_utils.py::get_skill_search_roots`; seeding `external_dirs` only pays when
    that carry is deleted (S3), and before then lists the root twice. The carry also serves
    every home the seed never reaches: the sweep fills persona-BOUND profiles only, so the
    root/head home and any unbound profile would lose the shared root when the carry goes.
    Needs: either the seed reaches every home that reads skills, or the carry stays for
    unbound homes. The value would be home-relative (`external_dirs` entries resolve against
    `HERMES_HOME`), never an absolute path.
    **RULED 2026-10-22 (owner): line 4 is not seeded; the shared-root carry in
    `agent/skill_utils.py` stays for the homes the sweep never seeds** (root/head home, unbound
    profiles). Recorded 2026-10-24, lane w1024t-hermes, row `RT-SEED-LINE4-UNBOUND-HOMES`; no
    code change, and S3's line-4 carry retirement is off the table.
  - Line 5 — DESIGN: nothing computes a placement's surface-incompatible skill set; only
    `agent_runtime/skill_view_result.py` refuses per call.
  - Line 6 — DESIGN: no `eternia-persona` toolset is registered (the lane composite is
    `harness_core`, `agent_runtime/harness_toolset.py`), and any seeded `toolsets:` moves
    every persona from `lane_default` to `profile_config` in `declared_lane_toolsets`.
  - Line 8 — DESIGN: the terminal envelope is command classes plus role/lane grants
    (`agent_runtime/terminal_envelope/`), with no glob form; a static `approvals.deny`
    would refuse what a grant allows.
  - S3 — not built: each carry retirement is an upstream-footprint change of its own.

## In plain English

Upstream hermes already has config switches that do most of what several of
our carried patches do — but only if each persona's `config.yaml` is filled in
with the right values when the persona is created. This page proposes those
values, one line per key, with the reason and what the operator would lose.
Approve, change or strike each line; then one lane writes them in the one
place personas are created.

## Evidence

- Source of every value: `docs/agent-runtime-harness/planned/door-fit-2026-09-27.md`
  (PARTIAL rows #124210, #124193, #124192, #124191, #123979, #123977,
  #125257, draft `issue-config-readonly-projection`) and its line "the
  launcher SEEDS every persona profile's `config.yaml`" — now hermes's job.
- Shared skills root: `agent_runtime/profile_home.py::get_shared_skills_dir`.
- Persona creation paths: `agent_runtime/agent_create/perform.py` and
  `agent_runtime/persona_profiles.py::promote_profile_to_persona` (S0 confirms
  the single writer); round-trip YAML writer `agent_runtime/yaml_io.py`.

## The draft values (approve per line)

| # | Key | Proposed default | Why (door-fit row) | What it costs |
| --- | --- | --- | --- | --- |
| 1 | `mcp_servers.<s>.env.HERMES_HOME` | `"${HERMES_HOME}"` on every stdio server block the persona gets | a child MCP resolves the spawning persona's home (#124210 d) | none |
| 2 | `credential_pool_strategies` | `{<each configured provider>: least_used}` | even spread with no `auth.json` write per select (#124193) | strict round-robin ORDER is lost (spread kept) |
| 3 | `skills.create_dir` | the shared skills root | new skills land in the one shared root (#124191) | — |
| 4 | `skills.external_dirs` | `[<shared skills root>]` | every persona indexes and views shared skills (#124191) | in-place `skill_manage patch` of a shared skill is refused (external) |
| 5 | `skills.disabled` | the persona's surface-incompatible skill set, computed at create | both walkers hide them (#125257) | recomputed only when placement changes, not per session |
| 6 | `toolsets` | `["eternia-persona", "<core bundle>"]` | the persona toolset is the profile's list (#123979) | — |
| 7 | `tools.tool_search.enabled` | **leave unset** (upstream `auto`) | #124192's all-or-nothing switch would make every MCP tool eager | chat tools stay deferrable (the 7b carry stays, as ruled) |
| 8 | `approvals.deny` | the persona's terminal envelope in glob form (empty for an unrestricted persona) | holds for every terminal caller, typed `blocked` result (#123977) | static only; runtime-changing envelopes keep the carry |
| 9 | `HERMES_MANAGED_DIR` | **not a config key** — an env var per hermes process; propose: the Launcher sets it to a managed dir it owns, hermes does not seed it | read-only projection of the router's loaded model (draft `issue-config-readonly-projection`) | per process, not per lane |

## Owner decisions (recommendation first)

1. **Approve lines 1–6 and 8 as written** (recommended).
2. **Line 7: leave unset** (recommended) — the switch is all-or-nothing.
3. **Line 9: launcher-owned env, not a hermes seed** (recommended) — it is a
   process setting, so "hermes seeds it on persona create" does not fit; this
   amends the 2026-10-03 ruling for this one key.
4. **Existing personas:** recommend a one-shot startup migration (same shape as
   `agent_runtime/persona_toolsets_migration.py`: round-trip writer, report,
   fail-open) that fills a key only when ABSENT — never overwrites an operator
   value.

## Slices (after approval)

- **S0 — name the single writer** of a new persona's `config.yaml`; if two
  exist, the first commit makes one.
- **S1 — seed on create** (`agent_runtime/persona_seed_defaults.py`, one table
  of the approved lines). Killing mutation: drop line 4 → a create test reading
  the new profile's `skills.external_dirs` reds. Positive control: an operator
  value present before create is preserved.
- **S2 — fill-if-absent migration** for existing personas. Killing mutation:
  overwrite instead of fill → the "operator value survives" test reds.
- **S3 — retire carries** each line makes redundant, per door-fit's Actions
  (close the PR/issue, delete the carry) — one commit per carry, footprint
  ledger updated.

## Amendment 2026-10-21 — lines 5, 6 and 8: the design gaps, planned (lane w1021i-plans)

Row `RT-SEED-DOOR-FIT-PARTIAL`. Read 2026-10-21 against `origin/main` d087df7035. Line 3 is RULED not
seeded; line 4 is `RT-SEED-LINE4-UNBOUND-HOMES`; lines 1–2 are landed. What follows is each held line
planned from the code, in the `persona_seed_defaults.py` writer S0 named (mint + startup sweep).

### Line 5 — `skills.disabled`: the computation exists per skill; the set is a walk over it

- **What is true:** `agent_runtime/skill_resolution.py::skill_frontmatter_runtime_compatibility(frontmatter,
  *, surface, root_node_mode)` is the one predicate (`skill_view_result.py` refuses per call with it;
  the index applies frontmatter `session_platforms` only). A persona's chat turn runs with
  `skill_surface="mission_chat"`, `skill_root_node_mode=False` (`persona_runtime.py`'s
  `AgentRunRequest`). Upstream reads `skills.disabled` ∪ `skills.platform_disabled.<platform>` in
  `agent/skill_utils.py::get_disabled_skill_names` (minus `ESSENTIAL_SKILLS`), from the profile's
  `config.yaml`, in BOTH walkers. The roots a persona sees are `get_skill_search_roots()` under its
  bound profile home (call-time `HERMES_HOME`, the `profile_home` context the sweep already enters).
- `Decided (plan):` **`persona_seed_defaults.incompatible_skills(home) -> frozenset[str]`:** walk every
  `SKILL.md` under the persona's search roots, parse frontmatter (`skill_view_result._frontmatter`'s
  reader, moved beside it), keep the names whose compatibility for `surface="mission_chat",
  root_node_mode=False` is false. Cost: one frontmatter read per skill, under the sweep that already
  parses each persona's `config.yaml`; recorded in the sweep receipt (`persona_seed.line5 {persona,
  skills, incompatible}`).
- `Decided (plan):` **the sweep OWNS the computed subset and never the operator's.** The writer
  gains a sidecar beside `config.yaml` — `seed_receipt.json` `{schema_version: 1, seeded: {"skills.disabled":
  [...]}}`, written by `seed_persona_profile` through `utils.atomic_json_write` — and on each sweep writes
  `skills.disabled = (current − previously seeded) ∪ freshly computed` — an operator entry survives,
  a skill that became compatible is released, a new incompatible shared skill is hidden on the next
  boot. Lines 1–2 stay fill-if-absent and record nothing in the sidecar. The two callers today are the
  mint (`persona_profiles.promote_profile_to_persona` → `seed_persona_profile`) and the plugin's startup
  sweep (`seed_all_persona_profiles`); the office placement door (`office_store/actor_writes.upsert_actor`'s
  persona arm, via the same `seed_persona_profile(home)` call) is the third, so a placement change
  recomputes without a restart.
- **Stage S5 test** (`tests/agent_runtime/test_persona_seed_defaults.py`): a home with one
  mission-chat-incompatible skill and one compatible → `skills.disabled == [incompatible]`; an operator
  entry `foo` set before the sweep survives a second sweep; marking the skill compatible releases it.
  Killing mutations: write `current ∪ computed` (never release) → the "released" test reds; drop the
  sidecar → the operator entry is dropped on the second sweep → red.

### Line 6 — `toolsets:`: no `eternia-persona` toolset exists, and any seed re-labels every persona

- **What is true:** the lane composite is `harness_core` (`agent_runtime/harness_toolset.py`);
  `persona_profiles.declared_lane_toolsets` resolves an absent / upstream-default `toolsets:` to the
  typed `lane_default` and anything else to `profile_config` verbatim; `tool-diff` shows the source.
  Door-fit #123979's remaining residue is upstream's `add_to_toolset`; its "seed the profile list"
  action assumed a persona toolset by that name, which was never registered.
- **The seed buys nothing the lane default does not already give**, and costs the typed distinction:
  after a seed every persona reads `profile_config`, and an operator can no longer tell a declared list
  from a seeded one. Registering `eternia-persona` as an alias of `harness_core` only to seed it is a
  second name for one composite (one owner per helper).
- **Open ruling** · Line 6: strike it (the lane default IS the persona toolset, typed), or seed
  `toolsets: [harness_core]` and teach `declared_lane_toolsets` to classify exactly that list as
  `lane_default`? · Recommend: **strike**; door-fit #123979 keeps its `add_to_toolset` residue
  unchanged and the row's line-6 gap closes as "not seeded, by design".

### Line 8 — `approvals.deny`: the envelope has no static glob form, by construction

- **What is true:** the envelope is four command CLASSES (`terminal_envelope/classes.py`: `git_push`,
  `destructive_git`, `recursive_delete`, `network_egress`, each a regex row mirrored from
  `tools/terminal_tool.py::_HARNESS_BLOCK_PATTERNS`, the network class with a localhost allowlist) lifted
  per role and per lane by operator GRANTS (`grants.py::resolve_terminal_envelope_grants`, governed lane
  `mission_chat` only). `decision.py::hard_floor_command_classes()` is EMPTY after ruling R-2: every
  class is grantable. Upstream's `approvals.deny` is fnmatch globs over the command string, checked in
  `tools/approval.py::_user_deny_block` BEFORE yolo, mode=off, the allowlist and the container path —
  "never bypassable" by design.
- So a seeded `approvals.deny` would refuse what a grant allows (the row's own sentence), for every
  class, and cannot express the network allowlist at all. Door-fit §Actions asked the owner exactly this
  ("static or runtime envelope; then close"); the code answers: runtime.
- **Open ruling** · Line 8: strike it (the envelope stays the fork's carry; #123977's PR stands for
  runtime envelopes), or seed only classes an operator has NOT granted for the persona's role, re-seeded
  on every grant change (a static mirror of a dynamic table — two write paths for one decision)? ·
  Recommend: **strike**; record on door-fit #123977 "envelope is runtime, not static — seed closed,
  PR stands".

### Status after this amendment

Line 5: READY with the stage above. Lines 6 and 8: BLOCKED owner decision (recommendations: strike
both). No other line of this plan changes.

**RULED 2026-10-22 (owner): lines 6 and 8 are struck** (recorded 2026-10-24, lane w1024t-hermes, row
`RT-SEED-LINES-6-8-STRIKE`). Line 6: not seeded, by design — the lane default (`harness_core`,
`declared_lane_toolsets` → `lane_default`) is the persona toolset; door-fit #123979 keeps its
`add_to_toolset` residue. Line 8: not seeded — the envelope is runtime (classes + grants), not a static
`approvals.deny`; door-fit #123977's PR stands for runtime envelopes. No code changes.

## Blast radius

The persona-create path, one new table module, one startup migration; each
persona's `config.yaml` gains keys. Upstream untouched.

## What it retires

Up to seven carried patches or open PRs (per door-fit's Actions) once their
config doors are filled, and the launcher-side seeding the 2026-10-03 ruling
moved to hermes.
