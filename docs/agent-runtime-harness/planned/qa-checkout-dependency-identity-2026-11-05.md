# Planned — a pinned QA checkout borrows the lender CHECKOUT's environment, not only the lender root (RT-QA-CHECKOUT-DEPENDENCY-IDENTITY, 2026-11-05)

**Status:** plan written by lane w1105g-hm-plan; build rows in §4. Group: `qa-runtime-checkout`.
**Owner domain:** pm / the dependency borrow ([04-boot-and-lifecycle.md](../04-boot-and-lifecycle.md) § the profile
namespace), and the launcher's Stage C QA launch (`hermes_checkout`).
**Read (code, no live run):** hermes `origin/main` `864cf9b45c` — `pm/environments.py::install_key` /
`install_state_dir` / `selected_venv` / `_recorded_venv` / `activate_dependencies` (the boot selection) and the fork
block at its foot (`_fork_borrowing`); `pm/_fork_dependency_borrow.py`; `pm/install_states.py` (the
`inputs/.project-root` record); `hermes_cli/runtime_state.py::runtime_lock`; the launcher's
`EterniaLauncher/tool/stagec_qa_mcp_server/lib/launch/launch_flow.dart` (`hermes_checkout`, `withPinnedCheckout`)
and `EterniaLauncher/tool/stagec_qa_mcp_server/lib/launch/launch_request.dart` (`kQaHermesDependencyRootEnv`).

## 0. The finding, as the tree has it

Dependency state is keyed twice: by DATA ROOT (`<root>/installs/`) and by CHECKOUT
(`install_key(project_root)` = the first 16 hex of `sha256(resolved checkout path)`). The borrow
(`HERMES_DEPENDENCY_ROOT`, owner ruling 2026-10-15) re-points only the first: `dependency_home_root` answers the
lender root, but `install_state_dir(project_root)` still hashes the RUNNING checkout. A QA launch pinned to a
worktree (`hermes_checkout`, launcher row QA-HERMES-SOURCE-CHECKOUT-OVERRIDE) runs the worktree's code, so it
looks under `<lender>/installs/<key(worktree)>/` — which never exists, since the lender only ever installed its
own checkout. `committed_venv` answers `None`, `activate_dependencies` falls to `_require_own_dependencies`, and the
store Python has no `ruamel`: startup fails. The primary checkout works because its key IS the lender's key.

## 1. Decisions (each vetoable)

**D1 — the lender names its checkout explicitly: `HERMES_DEPENDENCY_CHECKOUT=<absolute lender checkout>`.**
`Decided (plan):` beside `HERMES_DEPENDENCY_ROOT`, never alone. Set together, `install_state_dir(project_root)`
answers `<lender root>/installs/<install_key(lender checkout)>` for EVERY `project_root`; the running checkout's
own path still decides `sys.path` (its code runs). Alternatives weighed:
- *Infer the key from the lender root* (the one `installs/<key>/inputs/.project-root` there, or
  `<root.parent>/hermes-agent`): refused — a root holds one state per checkout it ever ran (this box's base root
  holds five), and a layout guess is a second, silent authority on which environment a QA run measured.
- *Grow `HERMES_DEPENDENCY_ROOT`'s value* (`<root>#<checkout>`): refused — every reader of the variable
  (`_namespace_bootstrap`, `agent_runtime.namespace`'s cache key, the launcher's facts reader) would have to learn
  the grammar.
- The rubric's "no new `HERMES_*` env var for non-secret config" does not bite: this is a process-launch
  contract the launcher hands a child, like `HERMES_DEPENDENCY_ROOT`, not a behaviour a user configures. Veto
  here if the owner reads it otherwise; the fallback is the inference above with a refusal on ambiguity.

Refusals (`BorrowedEnvironmentReadOnly`, the borrow's existing error): the checkout variable without the root
variable (`dependency_checkout_without_root`); a relative path; a lender checkout whose state dir under the
lender root has no committed environment (`lender_checkout_not_installed`, naming both paths) — never a fall
back to the running checkout's own key, which is the failure this row is.

**D2 — the borrow is honest only when the dependency inputs match; a mismatch refuses.** `Decided (plan):` at
selection, compare `sha256` of each `ACTIVATION_INPUTS` file (`uv.lock`, `pyproject.toml`, `pm/lock.json`) in the
running checkout and the lender checkout. Any difference refuses `dependency_inputs_differ` with the file list:
a worktree that changed its dependency set cannot be measured on the lender's environment, and a QA receipt
that passed on the wrong packages is a false green. Content, not mtime: the two checkouts' mtimes never agree.
Veto option: warn and proceed (a receipt field instead of a refusal) — not recommended.

**D3 — the running checkout's code wins every import.** `Decided (plan):` already true in `activate_dependencies`
(the checkout root is put first on `sys.path`, and setuptools/uv editable finders append to `sys.meta_path`
after the path finder), but it has never been pinned for a DIFFERENT checkout: S1's acceptance pins it, because a
borrowed environment's `__editable__` pointer names the lender checkout and a regression would silently run the
lender's code under the worktree's name.

**D4 — nothing new is written.** The borrower still never syncs (`refuse_sync_while_borrowing`), copies no
environment and changes no assignment data. It takes the lender's generation lease exactly as a same-checkout
borrower does today, so the lender's reclaim (`pm/install_states.py`) cannot collect the generation under it.

## 2. Where it lives

Fork-owned: `pm/_fork_dependency_borrow.py` grows `borrowed_checkout()` and the input comparison; the fork
block at the foot of `pm/environments.py` wraps `install_state_dir` the way it already wraps
`dependency_home_root` / `owning_home_root` (no module-scope import; the minted-launcher fixtures that copy the
file alone still import). `install_key` itself is untouched — the reclaim and `owning_home_root` keep hashing the
real checkout. Footprint: the fork block grows by the one wrap; re-derive the `pm/environments.py` ledger row.

## 3. The launcher half (not this repo's to build)

The QA launch that pins `hermes_checkout` hands the child `HERMES_DEPENDENCY_CHECKOUT=<the machine install's
code root>` beside `HERMES_DEPENDENCY_ROOT`, and the paired QA receipt reports `dependency_checkout`; an unpinned
launch sets neither. Then the appearance acceptance the row names runs on a pinned worktree.

## 4. Build rows (filed in `Harness_Brain/20 — Active Initiatives/runtime-queue.md`)

- `RT-QA-CHECKOUT-BORROW-LENDER-KEY` — D1 + D3. Tests in `tests/pm/test_dependency_borrow_downstream.py`: a temp
  lender root holding a committed environment under `installs/<install_key(lender)>`; a borrower checkout at
  another path with both variables set → `selected_venv(borrower)` is the lender's environment; checkout variable
  without the root variable, a relative path, and a lender key with no committed environment each refuse by
  name; a child process booted through `activate_dependencies` on the borrower imports `hermes_cli` from the
  borrower checkout (`__file__` under it). Killing mutation: drop the `install_state_dir` wrap → the first case
  answers the borrower's `base_venv` and reds.
- `RT-QA-CHECKOUT-BORROW-INPUTS-MATCH` — D2. Test: a borrower whose `uv.lock` differs by one byte refuses
  `dependency_inputs_differ` naming `uv.lock`; identical inputs select. Killing mutation: compare mtimes (or skip
  the comparison) → the one-byte case selects and reds.
