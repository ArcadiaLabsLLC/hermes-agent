# Planned — a phone's account data, in namespaces like the desktop's, deleted before the embedded serve starts — 2026-11-19

**Owner domain:** the embedded entry (`hermes_cli/harness_parts/serve/in_memory.py`), the namespace verbs
(`agent_runtime/namespace_admin.py`) and their bootstrap (`hermes_cli/_namespace_bootstrap.py`), the bundled phone
profile (`agent_runtime/bundle_profiles/bundled-phone.yaml`). Parent plan: Eternia
`EterniaLauncher/docs/embedded_hermes/planned/IN_PROCESS_WIRE_2026-11-15.md` §4.1 (removal) and §4.7 question 2
(RULED 2026-11-16: A, "yes namespaces like the desktop").
**Row:** `RT-PHONE-NAMESPACE-DELETE-BEFORE-SERVE` (group `phone-harness`, Eternia's `TASK-PHONE-HARNESS`). Its close
wakes Eternia's `MC-PHONE-ENGINE-REMOVE-AGENT-DATA-ON-NEXT-START`.
**Status:** BUILT 2026-11-19 (lane w1118a-hphone): S1-S4 as below; one change from S3 — after start only the served namespace is refused (the CLI's own `_refuse_own`), not every delete. **Read:** 2026-11-19 against hermes `origin/main` 99b433cdf2.
No owner decision is needed: every choice below is harness-internal, and the one owner question (A or B) is ruled.

## 1. What is true today (read in code)

- `configure_app_folder(app_dir)` sets `HERMES_HOME=<app>/hermes` and `HERMES_AGENT_RUNTIME_ROOT=<app>/hermes/agent-runtime`
  and nothing else: no `HERMES_NAMESPACE`, no `namespace.json`. A phone store is the base root.
- `namespace_admin.delete(ns_id, env)` is the desktop's one removal: `_refuse_own` (the env's `HERMES_NAMESPACE`),
  `existing_namespace` (the manifest names it), `_exclusive` (the socket lock, then the serve registry's live rows),
  then `_rm(root)`. Its typed refusals are `NamespaceRefused(...).payload()`, which `hermes namespace delete` prints.
- `namespace_admin` imports at module level `agent_runtime.serve_registry` (row constants, `list_serve_instances`,
  `serve_instances_dir`) and `agent_runtime.serve_socket.owner_lock` (`socket_lock_path`, `socket_owner_path`).
  The phone profile switches both off (`switched_off_modules`), and `serve_socket/__init__.py` imports the whole
  socket lane, so importing `owner_lock` alone is not possible. On a phone, then, `import namespace_admin` fails.
- Both modules answer only "is a SEPARATE serve process using this namespace" (a held socket lock, a live pid row).
  A phone has no separate serve process: the embedded shell writes no pid row and opens no socket. The one serve that
  can hold a phone namespace is the embedded one in the same process.
- The embedded serve starts once per process (`EmbeddedServe.start` raises on a second start) and binds one host
  store per process (`bind_host_store`; rebinding raises).

## 2. What changes

### S1 — `namespace_admin` loads without the switched-off modules

Move the two imports into the functions that use them (`busy_reason`, `_exclusive`, `_rows_busy`, `_last_serve`),
each through one helper, `_separate_serve_evidence()`, that returns the four callables or, on `ImportError` (the phone
bundle, which does not ship them), the phone's truth: no lock file path to hold and no registry rows. Desktop
behaviour is byte-for-byte the same (the modules are always there). The helper is the one place the absence is
answered, with a comment naming the profile switch; a test imports `namespace_admin` with both modules blocked
(`sys.modules[...] = None`) and deletes a namespace. Rejected: keeping `serve_registry` in the phone bundle (it is
switched off with the daemon shell on purpose) and splitting `owner_lock`'s two path functions into a new module
(a second home for two one-line path rules).

### S2 — the host names the account's namespace when it configures the app folder

`configure_app_folder(app_dir, namespace=None, origin=None)`:

- with no namespace: today's base-root layout, unchanged (a host that never names one keeps working);
- with one: the desktop's own resolution, never a second one — the base root stays `<app>/hermes`
  (`HERMES_DEPENDENCY_ROOT`), the namespaces dir is `<app>/hermes-namespaces` (`namespaces_dir`'s default),
  `HERMES_NAMESPACE=<id>` and `HERMES_LAUNCHER_SPAWNED=1` (the app is its own launcher, so no active record is read),
  over an env holding only `HERMES_HOME=<app>/hermes` (a preset store root there would be refused
  `namespace_home_escape`, rightly), then `resolve_cli([], env)` → `ensure_manifest(layout, requested_origin)` → `env_updates(...)`: the same
  `HERMES_HOME=<root>/profiles/base`, store root `<root>/agent-runtime`, head home and fences the CLI sets. A
  `NamespaceRefused` (an invalid id, a root too long, a store epoch newer than this build) is raised to the host,
  never a fallback to the base root; the payload is the CLI's.
- The host binds its store over `app_dir` (it already contains the namespaces dir), so `OutsideStoreRoot` is unchanged.
- Store epoch: the CLI path's guard is applied on configure (`epoch_admitted(..., write=True)`). A phone has no consent
  path for a raise; a newer store refuses typed (`namespace_epoch_newer`) and the host says "update Eternia".

### S3 — delete before serve, the CLI's verb in the embedded interpreter

`delete_namespace(app_dir, ns_id) -> dict` in `in_memory.py`, beside `configure_app_folder`:

- refuses `namespace_in_use_by_this_process` once `EmbeddedServe.start` has run in this process (a module-level mark
  the start sets; the serve cannot be stopped, so the namespace it serves is held until the process ends);
- builds the env `configure_app_folder` would give the BASE root (no `HERMES_NAMESPACE`), never touching
  `os.environ`, and calls `namespace_admin.delete(ns_id, env)`;
- returns the verb's dict, or the refusal's `payload()` — the same JSON `hermes namespace delete` prints, so the
  Eternia pass reads one shape on every platform.

The host's order at start: `delete_namespace` for every recorded removal → `configure_app_folder(app, namespace=…)`
→ `bind_host_store` → `EmbeddedServe.start`.

### S4 — packaging

The phone bundle must hold `agent_runtime.namespace_admin` (and `hermes_cli._namespace_bootstrap`, `store_epoch`,
`file_locks`). `in_memory.py` importing `delete_namespace`'s module lazily keeps it in the closure walk; a test reads
the phone profile's closure (`scripts/bundle_profile_closure.py::profile_walk`) and asserts `namespace_admin` is kept
and neither switched-off module is reached unguarded.

## 3. Tests (each watched red)

- `namespace_admin` imports and deletes with `serve_registry` / `serve_socket` blocked (S1; mutation: restore the
  module-level import → ImportError red).
- One process: configure with namespace A → delete namespace B (it existed with a manifest and files) → start the
  embedded serve in A → B's root is gone, A's `namespace.json` exists and A's home is `HERMES_HOME` (the row's
  "deletes one namespace then serves another in one process").
- `delete_namespace` after `EmbeddedServe.start` → `namespace_in_use_by_this_process`; an unknown id →
  `namespace_not_found`; `base` → `namespace_reserved`; each payload equals `hermes namespace delete`'s for the same
  case (S3; mutation: drop the started mark → red).
- `configure_app_folder` with an invalid id or a newer epoch raises the typed refusal and sets no `HERMES_HOME`.
- The phone closure keeps `namespace_admin` (S4).

## 4. Out of scope, cited

- Saved sign-ins: a phone's secrets live in the host store's slots (`hermes/v1/<profile>/<path under the store root>`),
  not on disk, so removing the folder leaves them — the same defect the desktop has, `RT-NAMESPACE-DELETE-LEAVES-SAVED-SIGN-INS`.
  One fix for both, on that row: the delete also forgets the slots of the namespace's secret files.
- Account switch inside one process (Eternia `MC-PHONE-ACCOUNT-SWITCH-NEEDS-AN-APP-RESTART`): one namespace per process.
- Eternia's pending-removal pass skipping the live namespace and being reached only through the pre-spawn gate
  (IN_PROCESS_WIRE §4.1): Eternia's half, `MC-PHONE-ENGINE-REMOVE-AGENT-DATA-ON-NEXT-START`.
