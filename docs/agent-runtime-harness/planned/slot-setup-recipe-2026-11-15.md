# Planned — the slot setup recipe, as its own design (2026-11-15, rewritten 2026-11-16)

**Owner domain:** workspace slots (`agent_runtime/workspace_slot*.py`, `agent_runtime/workspace_slots*.py`).
Parent plan `archive/build-running-work-2026-10-04.md` §3.5. Row `RT-SLOT-SETUP-RECIPE-SCOPED-DESIGN` (task
`TASK-SLOT-SETUP-RECIPE-DESIGN`). **Status:** designed and accepted by the owner (three rulings, 2026-11-15,
below); §2–§6 rewritten for the in-repository `.eternia/` folder on 2026-11-16 (lane w1115e-fh3), the
build's first step. The build slices of §6 and Eternia's row of §3 are filed under
`TASK-SLOT-SETUP-RECIPE-BUILD` (runtime queue) and Eternia's mission-control queue.

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

## Decisions, as ruled

The 2026-11-15 table proposed a synced recipe store; the third ruling replaced it with the repository
folder. What stands, in one place (the original table is in this file's history, `e0c2ff513c`):

| # | Question | Ruled answer | Source |
|---|---|---|---|
| 1 | Where does a recipe live? | **In the repository**, `.eternia/setup/` at its root, cloned and versioned with it. Nowhere else: no synced recipe store, no recipe in the slot document | third ruling (supersedes the table's 1) |
| 2 | What is in it? | Tools, env keys, the `.env`, and one install script **per platform**. The slot declaration keeps only what the slot IS: `repo`, `context`, `toolchain.kind` | table's 2 + second ruling |
| 3 | Who writes it? | Whoever commits to the repository. A recipe changes by a commit; hermes has no door that writes it | third ruling (supersedes the table's 3) |
| 4 | Does it ever gate anything? | **Never.** Ready is the checkout alone (RULED 2026-11-13). Nothing in the recipe blocks Ready, an assignment, a turn, a build or a landing gate | table's 4 |
| 5 | How does "varies by dev environment" show? | A recipe per platform (Windows, macOS, Linux); a computer reads only its own. Each computer may mark an item **Not needed here**, private to it (`machine_slot_env.json`), never synced | table's 5 + second ruling |
| 6 | Who sees a computer's step states? | Only that computer, read when Set up opens. The synced report keeps `bound`, `checkout`, `status`, `unknowns`; drops `tools`, `env_keys`, `dotenv` | table's 6 |
| 7 | When does anything run? | **Only on a click.** Set up starts blank; it shows the script's text before running it and runs it only when the person clicks Run. Nothing runs or is offered after a clone, a pull or a serve start | first ruling |
| 8 | What happens to today's in-declaration recipe? | Read and ignored, dropped at the slot's next write; no fold into a new store, no dual write | third ruling ("most of the synced-store merge and old-format fold drops out") |

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
the repository (cloned with it; the only home of a recipe)
  .eternia/setup/recipe.json     what Set up lists, per platform
  .eternia/setup/windows.ps1     install script, Windows
  .eternia/setup/macos.sh        install script, macOS
  .eternia/setup/linux.sh        install script, Linux
  .eternia/prompts/              reserved for prompts agents use here; NOT read by this design
slot document (shared with the workspace)
  slots.<name>     what the slot IS      repo, context, toolchain.kind        decides Ready (checkout)
  machines.<id>    each computer's report bound, checkout, status, unknowns
this computer only (machine_slot_env.json)
  workspaces.<ws>.<slot>   values (tool paths, env, PATH head, .env, venv) + skipped: [item ids]
```

**`recipe.json`, version 1** — one closed shape, read by one function (`read_recipe(checkout, platform)`):

```json
{
  "version": 1,
  "env_keys": [{"key": "OPENAI_API_KEY", "secret": true, "hint": "…", "url": "…"}],
  "dotenv": {"path": ".env", "example": ".env.example", "keys": [{"key": "API_BASE", "secret": false}]},
  "platforms": {
    "windows": {"script": "windows.ps1", "tools": [{"name": "flutter", "min_version": "3.47", "hint": "…", "url": "…"}]},
    "macos":   {"script": "macos.sh",    "tools": [ … ]},
    "linux":   {"script": "linux.sh",    "tools": [ … ]}
  }
}
```

- **Per platform.** `platforms.<this computer's platform>` is the recipe this computer sees: its `tools`
  and its `script`. `env_keys` and `dotenv` are shared by the platforms the file lists (a key is a key on
  every OS). A platform the file does not list reads as **no recipe** — the whole section is blank, keys
  included, so a computer never sees half of another OS's recipe.
- **Blank by default.** No `.eternia/setup/recipe.json` in the bound checkout, an unbound slot, or a file
  that does not parse as version 1: Set up shows the repository line and nothing else, plus one line
  saying why (`no_recipe`, `not_cloned`, `unreadable: <reason>`). Nothing is derived from the declaration
  to fill the gap.
- **Read from this computer's checkout, at the commit it is on.** The recipe is whatever the working tree
  holds when Set up opens; a teammate's change arrives with a pull, like any other file. Hermes never
  writes the folder and never reads another computer's copy.
- **Bounds.** `recipe.json` is at most 64 KiB; a script at most 256 KiB and must sit in `.eternia/setup/`
  (a `script` value with a separator or `..` is refused `script_outside_setup`). `hint` and `url` keep
  today's `credential_in_step` refusals (`url_carries_credential`, `text_carries_credential`): a
  credential-shaped hint makes the file `unreadable`.
- **Item ids** are stable and derived: `tool:<name>`, `env_key:<KEY>`, `dotenv`, `script`. A skip names an
  id; an id the file no longer has is ignored, never an error.
- **States on this computer:** `done`, `todo`, `unknown`, `skipped`; the script adds its last run
  (`running`, `succeeded`, `failed`, `stopped`, `lost`). `optional_missing`, `pending`, `blocking`,
  `notes` and `required` leave: nothing is required, so there is one kind of "not done".
- **Secret keys** are the recipe's `env_keys` and `dotenv.keys` marked `secret`, read from this computer's
  checkout (`secret_keys` keeps its name and callers; it takes the recipe instead of the declaration). A
  slot with no recipe has no secret keys, so the machine fill accepts any key for it — the same as a
  declaration with none today. This is a safety rule, not a gate.
- **One write path per state:** the recipe by a commit (none in hermes); the declaration by
  `slots.declare`; values and skips by `slot.env.set`; the report by the probe; a script run by
  `recipe.run_step`.

## 3. What Eternia's Set up shows

Per slot, two parts that never mix:

1. **The repository line** — Ready, Not cloned, Folder missing, Wrong repository, Unknown — with Clone and
   Locate. This is the checkout and the only thing that reads as a status.
2. **Setup** — blank unless this computer's checkout has a recipe for its platform (§2). When it has one:
   the tools, keys and `.env` with their state here, hint and link, and their action (Set a value or path
   through `slot.env.set`; **Not needed here** / **Needed after all**); then the install script as one
   item: its file name and the commit it is read from, **Show script** (the text, read-only), and
   **Run**, enabled only once the script has been shown. The heading counts what is left in neutral words
   ("2 left"), never as steps the slot waits on. There is no Edit: the recipe changes in the repository.

A slot card elsewhere in Eternia shows the repository line only.

`runtime.workspace.recipe.show` answers it, read-only: per slot `{ready, checklist, clone: step, recipe:
{platform, source: {path, commit}, items: [item + state + why], script: {id, path, sha256, last_run} | null,
left: n} | {platform, blank: no_recipe | not_cloned | unreadable, why}, runs}`; it reads the checkout and
probes this computer's tools when called, and writes nothing. **Show script** is
`runtime.workspace.recipe.script` (`{slot}` → `{path, commit, sha256, text}`), read-only.
`runtime.workspace.recipe.run_step` runs the script ONLY when the request carries the `sha256` the person
was shown; a script that changed since is refused `script_changed` and Eternia shows the new text. It stays
in `LOCAL_CONSOLE_METHODS` (a paired device never runs it) and keeps its `stale_request` / `step_running`
refusals; the run is the same visible background process as today (`process_registry.spawn_local`), in the
slot's checkout with its overlay: `powershell -NoProfile -File <script>` on Windows (`pwsh` where it is
installed), `bash <script>` on macOS and Linux, resolved through `agent_runtime.host_tools` (a shell door added there beside `git_command`; today it answers git and node only).

The Eternia row this design leads to (filed in Eternia's `mission-control-queue.md`, 2026-11-16):

> - **`MC-SLOT-SETUP-READS-THE-REPOSITORY-RECIPE` — Set up shows whether the repository is there, and, when the repository carries a setup recipe for this computer's platform, lists its tools, keys and install script; the script runs only when you click Run after reading it** · group: slot-setup-recipe-build · plan `hermes-agent/docs/agent-runtime-harness/planned/slot-setup-recipe-2026-11-15.md` §3 · architecture: Eternia renders the `recipe.show` answer and sends `slot.env.set` / `recipe.script` / `recipe.run_step`; no recipe logic in Flutter (backend-owned authority: the recipe is the runtime's read of the checkout) · designed, not built · done when: a slot whose checkout has no `.eternia/setup/recipe.json` shows the repository line and a blank Setup; one with a Linux recipe on a Linux computer lists its items with "2 left", "Not needed here" lowers the count on this computer only, and Run is disabled until Show script was opened; read live through `launcher_qa` · REQUIRES windows, linux · BLOCKED 2026-11-16: hermes — `RT-SLOT-RECIPE-READ-FROM-REPO` (the `recipe.show` answer it renders)

## 4. Moving off the in-declaration shape

There is no fold: the in-repository folder is the only home (§ Decisions 8).

- **Read.** `toolchain.tools`, `toolchain.env_keys`, `toolchain.dotenv` and `slots.<name>.recipe.steps` are
  ignored by every reader once slice 1 lands. `recipe.revision` keeps its second job — the slot record's
  edit counter the realm merge ranks by — and is renamed `slots.<name>.revision` in the same slice (read
  old, write new).
- **Write.** `slots.declare` accepts only `repo`, `context`, `toolchain.kind`; the first write to a slot
  stores it without the old keys. Nothing rewrites a document just because it was read.
- **`recipe.set` retires.** It wrote the owner's annotations and command steps into the slot document;
  with no recipe there it is refused `recipe_in_repository` for one release, then removed with its
  Eternia caller (slice 3).
- **Peers.** An older build that meets a new record sees empty tool lists and shows no recipe — the same
  blank a repository without the folder shows. A newer build reading an older peer's report ignores its
  `tools` / `env_keys` / `dotenv`.
- **Lost on purpose:** annotations and command steps someone typed into Eternia's old Set up. A team that
  wants them writes them into `.eternia/setup/` in a commit. Pre-launch; the owner's machines update
  together.
- **Other readers move to the recipe** read from this computer's checkout: `secret_keys` and the overlay's
  `.env` name (`workspace_slot_overlay.overlay_for`); `builds/detect.restart_unknowns` subtracts the
  recipe's keys instead of the declaration's.

## 5. Tests, each with its killing mutation

| Guarantee | Test | Killing mutation |
|---|---|---|
| A recipe never changes Ready | table over every item kind and state, recipe present and absent: `ready` and `checklist` equal the clone step's alone | read any recipe item's state in `readiness` |
| No recipe reads blank | checkout without the folder, an unbound slot, a v2 file, a 65 KiB file: `blank` with its `why`, no items | derive tool items from `toolchain.kind` when the file is missing |
| A computer sees only its platform | a file listing only `linux`, read as `windows`: blank, keys included | fall back to the first listed platform |
| A script outside the folder is refused | `"script": "../x.sh"` and `"script": "sub/x.sh"`: `unreadable: script_outside_setup` | resolve the script path without the containment check |
| Run needs the shown script | run with a stale `sha256`: `script_changed`, no process spawned; with the shown one: spawned once | skip the hash comparison |
| Nothing runs on its own | clone, bind and `recipe.show` a slot with a recipe: no `spawn_local` call | have the clone's completion call `run_step` |
| A skip is this computer's alone | set a skip, publish: the document and report carry no trace; the item reads `skipped` here | write `skipped` into `machines.<me>` |
| No tool or key state is published | the report row's keys are exactly `bound, checkout, status, unknowns, adopted_existing_root` | keep `tools` in the row |
| A secret key never enters the fill | today's `secret_in_env` test, with the key marked secret in `recipe.json` | read secret keys from `toolchain` only |
| The old shape has one fate | AST: `toolchain["tools"]` / `env_keys` / `dotenv` and `recipe.steps` are read nowhere | read `toolchain.get("tools")` in the probe |

## 6. Build slices, in order (filed 2026-11-16 under `TASK-SLOT-SETUP-RECIPE-BUILD`)

1. **`RT-SLOT-RECIPE-READ-FROM-REPO`** — `read_recipe(checkout, platform)` over `recipe.json` v1 and its
   bounds; `recipe.show`'s new `recipe` block (old keys kept for Eternia until slice 3);
   `recipe.script`; `secret_keys`, the overlay's `.env` name and `restart_unknowns` reading the recipe;
   `slots.declare` narrowed and `slots.<name>.revision`; `recipe.set` refused `recipe_in_repository`.
2. **`RT-SLOT-RECIPE-SCRIPT-RUN-ON-CLICK`** — `recipe.run_step` runs the platform script with the shown
   `sha256` (`script_changed`), the per-platform shell through `host_tools`; skips in the machine fill
   through `slot.env.set`; the report stops writing `tools` / `env_keys` / `dotenv`; the reduced state
   vocabulary.
3. **Eternia's Set up** (`MC-SLOT-SETUP-READS-THE-REPOSITORY-RECIPE`, §3), then
   **`RT-SLOT-RECIPE-OLD-ANSWER-KEYS-OUT`** — hermes removes `blocking`, `notes`,
   `orphaned_annotations`, the derived checklist and `recipe.set` once nothing reads them.

Each hermes slice is one lane; slice 2 follows slice 1 in the same files. `.eternia/prompts/` is not part
of this build; reading it is a separate design when an agent surface needs it.
