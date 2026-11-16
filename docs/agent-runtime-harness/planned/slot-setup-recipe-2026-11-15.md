# Planned — the slot setup recipe, as its own design (2026-11-15)

**Owner domain:** workspace slots (`agent_runtime/workspace_slot*.py`, `agent_runtime/workspace_slots*.py`).
Parent plan `archive/build-running-work-2026-10-04.md` §3.5. Row `RT-SLOT-SETUP-RECIPE-SCOPED-DESIGN` (task
`TASK-SLOT-SETUP-RECIPE-DESIGN`). **Status:** designed, not built, **waits on the owner** (lane
w1115k-hdesign). No build row is filed until the decisions below are accepted.

The owner's rulings, 2026-11-13: "a workspace slot recipe should probably be its own scoped design", and
on readiness, "it should just care if its source controlled" — tools and keys vary by dev environment.

## Owner ruling, 2026-11-15

> "sounds good and its blank by default and the user has to click set up to trigger it , never on its own"

All seven decisions below are accepted, with one amendment: **a slot's recipe starts blank** (no steps are derived and pre-filled from the declaration until someone writes them), and **nothing runs or is offered on its own** — the setup flow starts only when the person clicks Set up. Second amendment, same day:

> "and it should be a setup recipe per platform , different platforms likely will have different commands to install the enviorment"

So a slot has **one recipe per platform** (Windows, macOS, Linux), each with its own steps and revision, stored as `recipes.<slot>.<platform>`; a computer shows and runs only its own platform's recipe, and a platform with no recipe shows blank. This replaces decision 1's single recipe per slot and settles the "operating-system filter on each step" alternative in decision 5 the other way (whole recipes per platform, not per-step filters). Decision 5's per-computer "Not needed here" stays.

Third amendment, same day — the recipe lives IN THE REPOSITORY. Proposed: a standard folder at the repository root, cloned with it:

```text
.eternia/
  setup/
    windows.ps1   macos.sh   linux.sh   # install steps per platform
    recipe.json                         # what Set up lists: tools, keys, .env, which script to run
  prompts/                              # prompts agents use in this repository
```

Owner: "yes thats a good folder name tradeoffs are good". So: the `.eternia/` folder is the only home of a recipe (this supersedes decisions 1, 3 and 7 and the per-platform `recipes.<slot>.<platform>` store above — there is no synced recipe store); a recipe changes by a commit to the repository; a repository without the folder shows a blank Set up; Set up shows a script's contents before running it and runs it only on a click; decision 5's per-computer "Not needed here" stays local; decisions 2, 4 and 6 stand. **The build's first step rewrites §2–§6 of this plan for the repo folder.**

On a build, file the three slices in §6 and Eternia's row in §3 with this amendment.

## Decisions taken, owner may overrule

Standing order 2026-11-12: "if a decision comes up investigate fully and go with the recommended".

| # | Question | Option taken | Alternative rejected | Why |
|---|---|---|---|---|
| 1 | Where does a recipe live? | **Per slot, shared with the workspace**, as its own entry `recipes.<slot>` in the workspace's slot document, beside `slots`, `categories` and `guidance` | Per workspace (one list for every repository); per person only; a new store or sync family | A recipe is knowledge about one repository ("to work on this you need Flutter and these keys"), so it is keyed by the slot and worth sharing. The slot document already carries separately-merged entries (`categories.<name>`), so this needs no new file, door or family |
| 2 | What is in it? | **Every setup step**: tools, env keys, the `.env`, commands. The slot declaration keeps only what the slot IS: `repo`, `context`, `toolchain.kind` | Tools and keys stay in the declaration and the recipe only annotates them (today) | Being in the declaration is what made tools and keys read as part of "is the slot there". `toolchain.kind` stays because it is identity: the batch landing gate picks its command from it (`batch/gate.py::GATES_BY_TOOLCHAIN_KIND`) |
| 3 | Who is it for, and who writes it? | For the person (or their agent) setting the repository up on a computer. Written by anyone who may publish the workspace, through the one existing door `runtime.workspace.recipe.set` | A recipe each person writes for themselves | The shared part is the teammate's advice; the personal part is decision 5 |
| 4 | Does it ever gate anything? | **Never.** Ready is the checkout alone (RULED 2026-11-13). No recipe step blocks Ready, an agent's assignment, a turn, a build or a landing gate; a command still runs only on an explicit click | A `required` flag that blocks | The owner's ruling, and one fact needs one authority: the checkout answers "is the slot there" |
| 5 | How does "varies by dev environment" show? | Each computer may mark a step **Not needed here**. The mark is private to that computer (`machine_slot_env.json`, beside the values it already holds) and never synced | An operating-system filter on each step; a recipe per platform | A skip needs no taxonomy and covers every reason (another OS, a docs-only contributor, a tool installed another way) |
| 6 | Who sees a computer's step states? | Only that computer, read when Set up is opened. The synced machine report keeps `bound`, `checkout`, `status`, `unknowns` and drops `tools`, `env_keys`, `dotenv` | Keep publishing every computer's tool and key states to the workspace | Nothing decides anything from another computer's tools once they gate nothing, and every report today starts `<tool> --version` for every declared tool, a peer's declarations included |
| 7 | How do old records move? | Read old, write new, in one fold function; no dual write. An older build that meets a new record shows no recipe | A staged dual-field migration | Pre-launch; the owner's machines update together, and "no recipe" is a safe degrade |

## 1. What exists today (read on `origin/main` 28f52558)

- **Three stores, three scopes.** The slot document (`store/workspace_slots/<token>.json`, realm-synced,
  merged key-wise by `workspace_slots_sync`) holds `slots.<name>` = `{repo, toolchain: {kind, tools,
  env_keys, dotenv}, context, recipe: {revision, steps, edited_at, edited_by}}` and `machines.<id>` (each
  computer's report). The machine's private fill (`machine_slot_env.json`, 0600, never synced) holds tool
  paths, env values, PATH head, `.env` name, venv. The machine roots hold the checkout path.
- **The recipe is the declaration read as a checklist** (`workspace_slot_recipe.py`): `clone`,
  `tool:<name>`, `env_key:<KEY>` and `dotenv` steps are DERIVED from `repo` and `toolchain` and never
  stored; `recipe.steps` stores only annotations of those (`hint`, `url`) and the owner's `command` steps.
- **Readiness is already the checkout alone** (`readiness`, since `RT-SLOT-READY-IGNORES-TOOLS-AND-KEYS`,
  `0f7d2510826c`): a tool, key or `.env` left to do is `optional_missing`, a note. The module's own
  docstring still states the old rule (row `RT-SLOT-RECIPE-DOCSTRING-STATES-THE-OLD-READY-RULE`).
- **One counter does two jobs.** `recipe.revision` is also the slot record's edit counter: a
  re-declaration or a removal advances it (`workspace_slots._revised`), and the realm merge ranks a whole
  slot record by it first. So a teammate's recipe edit and another's re-declaration of the same slot are
  one decision: the higher counter takes `repo`, `toolchain`, `context` and `recipe` together.
- **Readers of the declared tools and keys:** the probe (`workspace_slots_probe._SlotProbe.row`, into the
  synced report), the secret rule (`workspace_slots.secret_keys`, which refuses a secret key's value in
  the machine fill and keeps it out of a command's environment unless it comes from the slot's `.env`),
  the `.env` name default (`workspace_slot_overlay.overlay_for`), and a build Restart's unknowns
  (`builds/detect.restart_unknowns`). None of them gates.
- **Reported, not read here:** the owner's 2026-11-13 screenshot ("To do: Create .env" on a slot whose
  folder has a `.env.example`). No hermes module reads `.env.example`; the declaration that carried the
  `dotenv` entry was written by Eternia.

## 2. The model

```text
slot document (shared with the workspace)
  slots.<name>     what the slot IS      repo, context, toolchain.kind        decides Ready (checkout)
  recipes.<name>   how to set it up      {revision, steps, edited_at, edited_by}   decides nothing
  machines.<id>    each computer's report bound, checkout, status, unknowns
this computer only (machine_slot_env.json)
  workspaces.<ws>.<slot>   values (tool paths, env, PATH head, .env, venv) + skipped: [step ids]
```

- **`recipes.<slot>`** is one decision with its own `revision` and `issued_at`, merged as `categories.<name>`
  is: one side's whole entry, the newer revision, then the newer stamp. A recipe whose slot is tombstoned
  or absent is kept and not shown (the slot may come back), as an orphaned annotation is today.
- **Steps are all stored**, in the author's order, one closed shape per kind (a table, `STEP_READERS`):

  | kind | fields | state on this computer |
  |---|---|---|
  | `tool` | `name`, `min_version?`, `hint?`, `url?` | found on PATH or the fill's tool path, version read |
  | `env_key` | `key`, `secret?`, `hint?`, `url?` | set in the fill or the environment |
  | `dotenv` | `path`, `keys: [{key, secret?}]`, `hint?` | file present, each key present |
  | `command` | `label`, `argv`, `cwd_slot`, `run`, `hint?` | offered or manual; its last run |

  `clone` stays the one DERIVED step (from `repo`), shown first, and is the only step that reads Ready.
  `required` is gone from every shape: nothing is required. The `credential_in_step` refusals stand.
- **Step states:** `done`, `todo`, `unknown`, `skipped` (this computer's mark), and a command's `offered` /
  `manual`. `optional_missing`, `pending`, `blocking` and `notes` leave: with nothing required there is one
  kind of "not done".
- **The slot record gets its own counter** (`slots.<name>.revision`), so a recipe edit no longer outranks
  or loses to a re-declaration.
- **One write path per state:** the recipe by `recipe.set` (publish right, optimistic `base_revision`,
  unchanged); the declaration by `slots.declare`; values and skips by `slot.env.set`; the report by the
  probe. The peer validator stays shared with the local one (`normalize_owner_step`, `held=True`).
- **Secret keys** are read from the recipe's `env_key` and `dotenv` steps instead of `toolchain`
  (`secret_keys` keeps its name and callers). This is a safety rule, not a gate.

## 3. What Eternia's Set up shows

Per slot, two parts that never mix:

1. **The repository line** — Ready, Not cloned, Folder missing, Wrong repository, Unknown — with Clone and
   Locate. This is the checkout and the only thing that reads as a status.
2. **Setup suggestions** — the recipe's steps in order, each with its state on this computer, its hint and
   link, and its action: Set a value or path (`slot.env.set`), Run (a command, `recipe.run_step`), and
   **Not needed here** / **Needed after all** (the skip). The heading counts what is left in neutral
   words ("2 suggestions left"), never as steps the slot waits on. A slot with no recipe shows no section.
   Edit (for a member who may publish) opens the step list; who edited it last is shown.

A slot card elsewhere in Eternia shows the repository line only.

`runtime.workspace.recipe.show` answers it: per slot `{ready, checklist, clone: step, recipe: {revision,
edited_at, edited_by, steps: [step + state + why], left: n}, runs}`; it probes this computer's recipe
steps when called and writes nothing.

The launcher row this design leads to (for the orchestrator once the owner accepts; not filed now):

> - **`MC-SLOT-SETUP-SHOWS-SUGGESTIONS-NOT-STEPS-TO-DO` — Set up shows whether the repository is there, and lists tools, keys and commands as suggestions you can mark "not needed here"** · group: slot-setup-recipe-design · plan `hermes-agent/docs/agent-runtime-harness/planned/slot-setup-recipe-2026-11-15.md` §3 · designed, not built · done when: a slot with its checkout in place reads Ready with two suggestions left, "Not needed here" removes one from the count on this computer only, and a slot with no recipe shows no suggestions section; read live through `launcher_qa` · REQUIRES windows, linux · NEW 2026-11-15 · BLOCKED 2026-11-15: hermes — `RT-SLOT-SETUP-RECIPE-SCOPED-DESIGN` waits on the owner's answer, then its build rows

## 4. Migration from the in-declaration shape

One pure function, `recipe_of(document, slot)`, is the only reader of the old shape:

- a document with `recipes.<slot>` answers it;
- otherwise it FOLDS the old record: `toolchain.tools` → `tool` steps, `toolchain.env_keys` → `env_key`
  steps, `toolchain.dotenv` → a `dotenv` step, each taking the `hint` / `url` of its old annotation, then
  the old `command` steps, in today's order; `required` is dropped.

The first write to that slot (`recipe.set` or `slots.declare`) stores `recipes.<slot>` and rewrites
`slots.<name>` without `tools`, `env_keys`, `dotenv` and without `recipe.steps`. Nothing rewrites a
document just because it was read.

- **Peers.** The pull validator (`held_document`) accepts both shapes and holds `recipes` through the
  step validator. An older build drops the `recipes` key it does not know and sees empty tool lists: it
  shows no recipe, loses nothing of its own, and its next publish lacks `recipes`, which a newer peer
  reads as "this side has none" (a union, never a removal).
- **The report.** A peer's row that still carries `tools` / `env_keys` / `dotenv` is read and those keys
  are not kept; this computer stops writing them.
- **The machine fill** gains `skipped`; a file without it reads as no skips. A secret key's value already
  in a fill is still refused and still kept out of a command's environment.

## 5. Tests, each with its killing mutation

| Guarantee | Test | Killing mutation |
|---|---|---|
| A recipe step never changes Ready | table over every step kind and state: `ready` and `checklist` equal the clone step's alone | read any recipe step's state in `readiness` |
| A recipe edit and a re-declaration do not overwrite each other | merge two peers' documents, one with a newer recipe and one with a newer declaration: both survive | rank the slot record by the recipe's revision |
| An old record reads as the same steps | fold fixtures of today's shape; the step list equals today's `materialize` order | drop the `env_keys` arm of the fold |
| The fold has one reader | AST: `toolchain["tools"]` / `env_keys` / `dotenv` are read only in `recipe_of` | read `toolchain.get("tools")` in the probe |
| A skip is this computer's alone | set a skip, publish: the published document and report carry no trace; the step reads `skipped` here | write `skipped` into `machines.<me>` |
| No tool or key state is published | the report row's keys are exactly `bound, checkout, status, unknowns, adopted_existing_root` | keep `tools` in the row |
| A secret key still never enters the fill | today's `secret_in_env` test, with the key declared by a recipe step | read secret keys from `toolchain` only |
| A peer's bad step drops alone | today's held-step tests over the four stored shapes | skip validation for `tool` steps |

## 6. Build slices, in order (to be filed when the owner accepts)

1. **The recipe entry and the fold** — `recipes.<slot>`, the four step shapes and `STEP_READERS`,
   `recipe_of`, `recipe.set` writing the new entry, `slots.<name>.revision`, the sync merge and validator
   for both shapes, `secret_keys` and the overlay reading through `recipe_of`. `recipe.show` keeps today's
   answer shape plus the new `recipe` block, so Eternia keeps working.
2. **States are local** — `recipe.show` probes on demand, the report stops writing `tools` / `env_keys` /
   `dotenv`, `skipped` in the machine fill through `slot.env.set`, the reduced state vocabulary.
3. **Eternia's Set up** (launcher row above), then hermes removes the old answer keys (`blocking`,
   `notes`, `orphaned_annotations`) once nothing reads them.

Each hermes slice is one lane; slice 2 follows slice 1 in the same files.
