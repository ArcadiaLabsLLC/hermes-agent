# Planned — a generated-document path handed to a host file tool is taught, never routed (RT-GENERATED-TREE-HOST-PATH-TEACH, 2026-10-31)

**Owner domain:** the chat turn lane ([05-chat-turn-lane.md](../05-chat-turn-lane.md)), tool results.
**Status:** plan written by lane w1031a-h; build rows in §4.
**Read (code, no live turn):** hermes `origin/main` `bbae8b3a8c` — `tools/file_tools.py::read_file_tool` /
`search_tool` (upstream: the `File not found:` / `Path not found:` answers `_record_not_found` keys on),
`write_file_tool` / `patch_tool` (upstream), `model_tools._apply_transform_tool_result_hook` (first string
wins), `plugins/eternia-harness/__init__.py::refuse_tool_call` (the plugin's ONE `pre_tool_call` callback),
`agent_runtime/launcher_app_functions.py::_offered_to_bound_link` (the bound Launcher link's catalog, read
at call time), and the launcher's tree verbs in
`EterniaLauncher/lib/core/services/hermes/runtime/data/capabilities/harness_generated_capabilities.dart`.

## 0. The finding

A model handed `/doc/components/logic/main.luau`, `/runtime/…` or `/ref/schemas/<C>.json` (from
`launcher_generated_inspect`, `launcher_generated_list` or the catalog guidance) reaches for `read_file` /
`search_files` / `write_file` / `patch`. Those resolve the path on the HOST: a read answers a host miss the
model then reasons about, and a write can CREATE the path — on Windows `/doc/x` is `C:\doc\x`, writable by
the user. The row asks for a refusal that names the `launcher_generated_*` verb: teach, never route.

## 1. What the NEEDS PLAN segment asks, answered

**Q1 — how a generated path is told from a real host path (a POSIX host can have a real `/doc`).**
`Decided (plan):` a call is a generated-tree call only when ALL THREE hold:

1. **Shape.** The path argument AS GIVEN (before the tool resolves it against a cwd) is POSIX-absolute
   with a first segment of exactly `doc`, `runtime` or `ref` (`/doc`, `/doc/…`). `doc/x`, `./doc/x`,
   `C:\doc\x` and `/Doc/x` never match: the tree is rooted and case-exact. For a V4A `patch`, every
   header path (`tools/file_tools.py::_collect_v4a_header_paths`) is tested; one generated path is enough.
2. **The host does not have it.** A read never shadows a hit: `read_file` / `search_files` are taught only
   when the host's own answer was the miss (`error` starting `File not found:` / `Path not found:`), so a
   host with a real `/doc` reads it exactly as today. `write_file` / `patch` cannot miss — they create — so
   they are refused before running only when the host has no top-level `/<segment>` at all (the existence
   probe of `/doc`, `/runtime`, `/ref` on the host filesystem, injected for tests). A host with a real
   `/doc` writes there as today. A sandbox backend (`_file_ops_uses_host_paths` false) keeps upstream's
   behaviour for writes in this plan; its reads are covered by the same miss rule.
3. **The verb is offered.** The turn's bound Launcher link lists the verb the teach would name
   (`_offered_to_bound_link`, made public as `offered_to_bound_link`). No link — the CLI, the gateway, a
   Launcher without the generated set — means the upstream answer, unchanged.

**Q2 — is the signal a generated document in the turn's context?** `Decided (plan):` **no.** A `/ref/…`
path reaches the model from `launcher_generated_list` and the catalog guidance before any document exists,
and a `/doc/…` path from a pasted message; reading the transcript for an `inspect` result on every file call
is a second authority on "which document is open" and a cost on the hottest tool path. Clause 3 is exact
about the one thing the teach needs (the verb it names exists THIS turn), and clause 2 settles the
collision. The `document_id` is the model's to supply, as the Launcher verbs already require.

## 2. The answer the model gets

| tool | when | answer | names |
|---|---|---|---|
| `read_file` | miss + Q1 | the miss, plus `generated_tree: {path, use, why}` | `launcher_generated_read` |
| `search_files` (`content`) | miss + Q1 | the same | `launcher_generated_grep` |
| `search_files` (`files`) | miss + Q1 | the same | `launcher_generated_tree`, its `pattern` as the tree's `glob` (a content search's `file_glob` rides to grep's) |
| `write_file`, `patch` | Q1 (before running) | `pre_tool_call` block: "a generated-document path; this tool writes the host filesystem" | the twin, `launcher_generated_write` / `launcher_generated_patch` (built, NEW-VERBS); `launcher_generated_edit` (by-path `replace` / `write` operations) when the link offers no twin |

`why` says it once: the path is a generated document's tree path, not a host file; call the named verb with
the `document_id` from `launcher_generated_inspect`. The hook never calls a Launcher verb itself (teach,
never route — the Launcher stays the one authority, and an `edit` is the person's to accept).

## 3. Where it lives

Fork-owned, no upstream edit: a pure `agent_runtime/generated_tree_teach.py` (the shape test, the verb map,
the two message builders; host probe and offered-verb check injected), read by a branch of the plugin's
existing `refuse_tool_call` (`pre_tool_call` is one callback by design) and by a third
`transform_tool_result` callback beside `skill_view_result` / `terminal_block_result` (first string wins,
and the three key on disjoint tool names). Tree vs row: the row points at `tools/file_tools.py` because the
miss is produced there; the fix rides the plugin's hooks, so the upstream footprint does not move.

## 4. Build rows (filed in `Harness_Brain/20 — Active Initiatives/runtime-queue.md` § Fork-owned)

- `RT-GENERATED-TREE-TEACH-READ` — §1 Q1 and §2's read rows. Test: a `read_file` miss on `/doc/components/
  x/main.luau` with a bound link offering `launcher_generated_read` carries `generated_tree.use`; positive
  controls — the same call with the host probe answering a HIT (a real `/doc`) is upstream's bytes; no link
  is upstream's bytes; `doc/x` (relative) is upstream's bytes. Killing mutation: drop clause 2 (teach on any
  shape match) → the real-`/doc` control reds. A ContextVar check through the real `handle_function_call`
  proves the link is bound where the hook runs (a tool on a worker thread).
- `RT-GENERATED-TREE-TEACH-WRITE` — §2's write row. Test: `write_file` and a V4A `patch` naming
  `/ref/format.md` are blocked naming `launcher_generated_edit`, with nothing written; positive control —
  the host probe saying `/ref` exists lets the call through. Killing mutation: drop the V4A header walk →
  the `patch` case reds.
- `RT-GENERATED-TREE-TEACH-NEW-VERBS` — when the launcher's `launcher.generated.patch` / `.write` /
  `glob` land, the verb map names them (`patch` → patch, `write_file` → write, `search_files files` →
  glob); blocked on the launcher's companion-queue rows.
