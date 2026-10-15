# Default seed values for the door-fit PARTIAL keys on persona create (draft for owner approval)

Status: DRAFT VALUES — written 2026-10-15 for the owner to approve, per the
2026-10-10 ruling ("orchestrator drafts default seed values from
door-fit-2026-09-27.md for the owner to approve"); no seed lands before
approval. Row: runtime-queue, "Seed the door-fit PARTIAL keys … on persona
create — HERMES seeds them, not the launcher" (owner, 2026-10-03).

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

## Blast radius

The persona-create path, one new table module, one startup migration; each
persona's `config.yaml` gains keys. Upstream untouched.

## What it retires

Up to seven carried patches or open PRs (per door-fit's Actions) once their
config doors are filled, and the launcher-side seeding the 2026-10-03 ruling
moved to hermes.
