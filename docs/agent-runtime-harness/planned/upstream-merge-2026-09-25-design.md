# Upstream merge 2026-09-25 — design for the next weekly merge (lane MERGE-DESIGN)

**Lane:** MERGE-DESIGN (design sitting: no merge, no production code; branch `lane/merge-design`, cut from
`origin/main` @ `9e5c578673`). **Queue row:** `Harness_Brain/20 — Active Initiatives/fork-hygiene-queue.md`,
"Next weekly merge: upstream `27df3b8847`…". **Rules of record:** `Harness_Brain/50 — Agent Handoffs/Merging
upstream.md` (the steps), `Harness_Brain/30 — Decisions/0006 …` (a real merge, weekly, in a worktree),
[`harness-plugin-and-upstream-seams.md`](harness-plugin-and-upstream-seams.md) §1 rules 9 and 10 (adopt
upstream's; a second door is a duplicate authority), `Harness_Brain/10 — Programs/Upstream Sync.md` § Each merge
(the supersession pass).

The note answers one question: what the merge lane must do so that `hermes harness serve` still boots and
`hermes postinstall` still completes after `upstream/main` is merged, and what every other conflict resolves to.

---

## 1. Sizing — from the tree, not the row

Taken 2026-09-25 with `git merge-tree --write-tree origin/main upstream/main` after `git fetch upstream`
(`origin/main` = `9e5c578673`, `upstream/main` = `ac2ffe60d0`, merge base `749220ef00`). The row was sized at
`27df3b8847` on 2026-09-24; the tree has moved since and the tree wins:

| | the row said | the tree says today |
|---|---|---|
| upstream tip | `27df3b8847` | `ac2ffe60d0` (2026-09-25 13:49 −0500) |
| range | "3,390 files" | `749220ef00..ac2ffe60d0`: **1,831 commits** (219 first-parent), 3,785 files, +221,722 / −97,815 |
| conflicts | 54 files / 73 hunks | **55 files** — 53 content conflicts carrying **74 hunks**, plus **2 modify/delete** |
| deleted modules fork code imports | `agent/ssl_guard.py` ← `hermes_cli/harness_parts/serve.py`; `hermes_cli/dep_ensure.py` ← `hermes_cli/_downstream_cli.py` | the same two modules; the serve importer is **`hermes_cli/harness_parts/serve/boot.py`** (`_prewarm_provider_runtime`) — `serve.py` was split into a package after the row was written |

`27df3b8847` ("bundles & unified installer") is a MERGE commit (parents `749220ef00`, `f05c6c522a`) and both
deletions ride under it: `2f20ceb6f7` "refactor(tls): trust the OS certificate store, one resolver" deletes
`agent/ssl_guard.py`, `agent/errors.SSLConfigurationError`, `tests/agent/test_ssl_ca_guard.py`,
`tests/hermes_cli/test_certifi_repair.py` and rewrites `agent/ssl_verify.py` around `install_truststore()`;
`5e4a2a3d24` "refactor(pm): remove legacy dependency and launch managers" deletes `hermes_cli/dep_ensure.py`
(and `tests/hermes_cli/test_dep_ensure.py`) in favour of the `pm/` package (`pm.ensure`, `pm.installed_package`,
`pm.shell.bash`, `pm.lazy_installs_allowed`).

**Every upstream-deleted non-test module, and who still imports it in the MERGED tree** (`git grep` over the
merge-tree result `9677e0339d`; eight modules deleted in the range — `agent/ssl_guard.py`,
`hermes_cli/dep_ensure.py`, `hermes_cli/gateway_service_unit.py`, `hermes_cli/plugin_python_deps.py`,
`hermes_cli/update_cmd_deps.py`, `scripts/ci/publish_e2e_evidence.py`, `scripts/install_psutil_android.py`,
`tools/environments/local_gitbash_probe.py`; six have no importer left):

| deleted module | production importer in the merged tree | fork test files importing it |
|---|---|---|
| `agent/ssl_guard.py` | `hermes_cli/harness_parts/serve/boot.py` (`verify_ca_bundle` in `_prewarm_provider_runtime`) | `tests/agent/test_shared_ssl_context.py` |
| `hermes_cli/dep_ensure.py` | `hermes_cli/_downstream_cli.py` (`ensure_dependency`, `ensure_git_bash`, `_DEP_CHECKS` in `cmd_postinstall`) | `tests/hermes_cli/test_postinstall_noninteractive.py`, `tests/hermes_cli/test_dep_ensure_downstream.py`, `tests/tools/test_find_bash_windows.py` (one import of `_resolve_windows_git_bash`) |

Every OTHER importer on `origin/main` today — `agent/agent_init.py`, `hermes_cli/doctor_platform.py`
(`verify_ca_bundle`), `acp_adapter/entry.py`, `hermes_cli/main_tui_launch.py`, `tools/browser_tool_install.py`
(`ensure_dependency`) — is an upstream file whose upstream version already carries the re-seat, and none of them
conflicts: the merge takes upstream's re-seat for free. The deleted upstream tests the fork had edited in place
(`test_ssl_ca_guard.py`, `test_certifi_repair.py`, `test_dep_ensure.py`,
`test_dep_ensure_noninteractive_spawn.py`, `tests/tools/test_browser_homebrew_paths.py`) are not in the conflict
list either: the fork had not touched them since the base, so the merge deletes them cleanly.

Two deleted SYMBOLS matter beyond the modules: `agent.errors.SSLConfigurationError` (only `ssl_guard` raised
it; the fork's `hermes_cli/doctor_platform.py` catch of it is inside an upstream hunk the merge replaces) and
the certifi premise itself — `agent/process_bootstrap.py`'s fork-added `shared_ssl_context()` (ledger row, class
G4, +70/−3) memoizes a certifi bundle parse that the truststore design no longer performs. §2.1 rules on it.

**Upstream test helpers that replace fork ones in the conflicted tests:** upstream now ships
`tests/_fixtures/platform_gating.py` (the `@pytest.mark.platforms(...)` mark), `tests/_fixtures/live_system_guard.py`
and `tests/_fixtures/env_filter.py` (the blocks `tests/conftest.py`'s two 300/550-line hunks were carved out of);
the fork's `tests/_home_env.py` and `tests/_fork_scope.py` stay fork-only.

**A prerequisite the lane pays before any test runs:** upstream adds the `truststore` dependency
(`pyproject.toml` +5 in `2f20ceb6f7`); the shared test venv `C:/Users/beast/.venvs/hermes-test` does not have it
(`import truststore` → `ModuleNotFoundError`, checked 2026-09-25). Install it first, as `snowballstemmer` and
`firecrawl-anydoc` were at the 2026-09-24 merge.

---

## 2. The two re-seats (rule 9: ADOPT upstream's replacement; never a parallel)

### 2.1 serve's CA check → `agent.ssl_verify.install_truststore()`

**What upstream provides now.** `agent/ssl_verify.py` is the one TLS authority: `install_truststore()`
(idempotent, never raises, returns `bool`; patches `ssl.SSLContext` process-wide through `truststore`) and
`resolve_httpx_verify(...)`, which itself calls `install_truststore()` and hands httpx a shared context
(`_shared_context`) only for an explicit `ssl_ca_cert` or a set `SSL_CERT_FILE`/`SSL_CERT_DIR`. Upstream's own
call sites — `agent/agent_init.py` (in the exact line the fork's `verify_ca_bundle()` occupied),
`hermes_cli/main.py`, `run_agent.py`, `acp_adapter/entry.py`, `tui_gateway/entry.py`,
`hermes_cli/doctor_platform.check_certificates` (which now reports "platform trust store configured" instead of
validating certifi) — all call `install_truststore()` at process start. There is no CA-bundle preflight left
to keep: a missing or corrupt certifi bundle is not a failure mode the platform verifier has, and the
`HERMES_CA_BUNDLE` / `HERMES_SKIP_SSL_GUARD` env reads leave with `ssl_guard` (nothing in the launcher sets
either — checked 2026-09-25).

**Fork function that changes:** `hermes_cli/harness_parts/serve/boot.py::_prewarm_provider_runtime` (fork-only
file). Its second step becomes

```python
    try:
        from agent.ssl_verify import install_truststore

        install_truststore()
    except Exception:
        pass
```

with the docstring's "a broken CA bundle … surfaces on the first real turn with its normal typed error"
sentence rewritten (there is no typed CA error any more; `install_truststore()` logs a warning and returns
`False` when truststore is unavailable). The first step's `shared_ssl_context()` call is ruled below; the
`load_openai_cls()` warm and the `get_tool_definitions` warm are untouched.

**The recorded parallel that retires with it.** `agent/process_bootstrap.py`'s fork-added `shared_ssl_context()`,
`_ssl_context_fingerprint()`, `_SSL_CONTEXT_CACHE` and the `build_keepalive_http_client` hunk that feeds the
memoized context into transports (ledger row `agent/process_bootstrap.py`, +70/−3, `upstream`, class G4) exist
to avoid re-parsing certifi's bundle three times per chat turn. Under truststore no bundle is parsed: the
default context defers to CryptoAPI / Security.framework / OpenSSL's store, and upstream's
`resolve_httpx_verify` already shares the one context that IS expensive (an explicit `ssl_ca_cert`). The memo is
therefore a parallel of upstream's `_shared_context` whose premise is gone, and rule 9 says adopt: **delete the
fork's `shared_ssl_context` family and the `build_keepalive_http_client` verify-forwarding hunk in the merge
lane, drop the `shared_ssl_context()` step from `_prewarm_provider_runtime`, and re-measure serve's first-turn
latency on the merged tree with the boot timeline the serve test already captures** (the ~900 ms/turn figure
in the fork's test docstring was measured against certifi; if the merged tree's first turn regresses instead,
that is a NEW finding to row, not a reason to keep a memo of a parse that no longer happens). The ledger row
and PR **#121647** (`up/ssl-ca-memo`, "perf(ssl): parse the CA bundle once per CA configuration", OPEN upstream
as of 2026-09-25) **retire together**: the PR proposes memoizing a verification upstream has deleted, so it is
closed as superseded by `2f20ceb6f7` with a one-line comment, not rebased. The `agent/ssl_guard.py` ledger row
(+33/−0, "PR candidate: memoize a successful CA-bundle verification per CA fingerprint") leaves the ledger with
the file.

**Tests.**
- `tests/agent_runtime/test_harness_serve.py` already pins the RELATIONSHIP that matters at the serve level —
  the boot captures `serve_boot._prewarm_provider_runtime` as the provider prewarm and runs it after the first
  build — and is unchanged.
- The re-seat itself gets one fork-only unit test beside it (new module in `tests/agent_runtime/`, name it
  `test_serve_prewarm_truststore.py`): monkeypatch `agent.ssl_verify.install_truststore` with a recorder, call
  `_prewarm_provider_runtime()`, and assert it was called exactly once; a second case makes the recorder raise
  and asserts the prewarm still returns. That is the relationship (prewarm → upstream's one authority, failure
  isolated), not a snapshot of the function body. Killing mutation to record in the commit body: replace the
  `install_truststore()` call with `pass` — the first case reds on `calls == []`.
- `tests/agent/test_shared_ssl_context.py` (fork-only; imports `agent.ssl_guard` at module level, so it fails to
  COLLECT on the merged tree) is deleted with the memo it pins. If the owner keeps the memo (§5 Q2), the file
  instead loses its `ssl_guard` import and its three `verify_ca_bundle` cases and keeps the two
  `shared_ssl_context` cases.
- `tests/agent/test_warning_presentation.py` and `tests/acp_adapter/test_entry.py` are upstream files whose
  merged versions no longer name `ssl_guard` / `dep_ensure` (checked in the merge-tree result); nothing to do.

### 2.2 `hermes postinstall` → upstream's package manager (`pm`)

**What upstream provides now.** `pm/` is the one installer: `pm.ensure(name, *, explicit=False, …)` installs a
locked package and returns a `Runner` whose `.env["PATH"]` carries its binaries (`explicit=True` marks "a
deliberate install command — those ARE the remedy the lazy-install policy points at", which is exactly what a
post-install bootstrap is); `pm.installed_package(name)` reads the selected entry without installing;
`pm.lazy_installs_allowed()` is the consent policy (`security.allow_lazy_installs`, `HERMES_DISABLE_LAZY_INSTALLS`
for Docker and the hermetic test harness); `pm.InstallError` is the typed failure; `pm.shell.bash()` is the one
bash resolver (store-staged bash first, then `windows_bash_candidates` — which honours `HERMES_GIT_BASH_PATH`,
Git for Windows roots, `%LOCALAPPDATA%\hermes\git`, and drops the System32 / WindowsApps stubs — then PATH).
The lock (`pm/lock.json`) names `node`, `npm`, `agent-browser`, `chromium`, `ripgrep`, `ffmpeg`, `git`
(win32-only PortableGit, `optional=True`), `gh`, `uv`, `python`, `tirith`, the `llamacpp-*` engines and more.
Upstream's own consumers show the shape: `acp_adapter/entry._run_setup_browser` is now
`pm.ensure("agent-browser", explicit=True)` inside `except (pm.InstallError, OSError)`;
`hermes_cli/main_tui_launch._tui_node_bin` is `shutil.which(bin, path=ensure(bin).env["PATH"])`;
`tools/browser_tool_install` asks `pm.installed_package("agent-browser")` for readiness and `ensure("chromium")`
only under `lazy_installs_allowed()`. Upstream has no `hermes postinstall`; the fork's remains the launcher's
entry point (`hermes postinstall --yes --json`, schema `hermes.postinstall/1`, of which the launcher reads only
`git_bash_path` — `lib/features/mission_control/data/install/hermes_postinstall_verify.dart`, checked
2026-09-25 — so the schema is kept as is).

**Fork function that changes:** `hermes_cli/_downstream_cli.py::cmd_postinstall` (fork-only file, registered by
the harness plugin). Hunk by hunk:

| today (`dep_ensure`) | after (upstream `pm`) |
|---|---|
| `ensure_dependency(dep, interactive=…)` for `node`, `browser`, `ripgrep`, `ffmpeg` | `pm.ensure(name, explicit=True)` for `node`, `agent-browser`, `ripgrep`, `ffmpeg`, each inside `except (pm.InstallError, OSError)` that prints the failure and continues (today's `False` return was non-fatal too). `chromium` is NOT ensured here: upstream installs it lazily on first browser use under `lazy_installs_allowed()`, and the fork ensuring it eagerly would be the second door of rule 10. |
| the `[Y/n]` prompt on a TTY (`interactive=…`) | gone — consent is pm's policy, and `explicit=True` is the deliberate-install signal. `--yes` / `--non-interactive` keep their one remaining meaning (skip the provider setup wizard). |
| `ensure_git_bash(interactive)` → `_resolve_windows_git_bash()` (upstream `_find_bash`) → `install.ps1 -Ensure git` → persist `HERMES_GIT_BASH_PATH` User-scope via `hermes_cli.windows_env` | a fork-only `_ensure_git_bash()` in `_downstream_cli.py`: `pm.shell.bash()`; when `None` on Windows, `pm.ensure("git", explicit=True)` then `pm.shell.bash()` again; POSIX unchanged (`shutil.which("bash")` is what `pm.shell.bash()` returns there). **No env-var persistence:** `pm.shell.bash()` finds the store-staged bash first, so a pm-installed Git needs no `HERMES_GIT_BASH_PATH` to be found by a fresh process; writing it was the second door (rule 10 — upstream's resolver already reads the env var when an operator sets it, and `hermes_cli/uninstall.py` still clears it for legacy installs). §5 Q3 lets the owner keep the persistence for one release; the launcher does not depend on it — it reads `git_bash_path` off the JSON and stores it itself. |
| `_DEP_CHECKS` → the JSON `deps` map keyed `node/browser/ripgrep/ffmpeg/git/git-bash` | the same keys, computed as `pm.installed_package(pm_name) is not None` (`browser` → `agent-browser`, `git-bash` → `pm.shell.bash() is not None`, `git` → `shutil.which("git") or pm.installed_package("git")`). Keys unchanged so `hermes.postinstall/1` stays `/1`. |
| the `hermes_cli.dep_ensure` import in `cmd_postinstall` | `import pm` at the top of `cmd_postinstall` (the function-local import style the file already uses; `pm` is a top-level upstream package the plugin may import — rule 3's fence is about fork EDITS to upstream files, and this is a public upstream API). |

The `scripts/install.ps1` fork hunk that added `git` / `git-bash` to `-Ensure` (ledger row `scripts/install.ps1`,
"…`git`/`git-bash` in `--ensure`") loses its only caller with `dep_ensure` and is not re-applied (§3 takes
upstream's installer wholesale). `hermes_cli/windows_env.py` (fork-only) loses its `set_user_env` /
`broadcast_environment_change` caller from postinstall; it keeps its other callers (`hermes_cli/path_setup.py`)
and is not deleted in this merge.

**Tests.**
- `tests/hermes_cli/test_postinstall_noninteractive.py` (fork-only) is re-seated, not rewritten: `_patch_common`
  monkeypatches `pm.ensure` with a recorder (`lambda name, **kw: calls.append((name, kw.get("explicit")))`),
  `pm.installed_package` with `lambda name, **kw: None`, and `pm.shell.bash` with the constant path the
  `ensure_git_bash` stub returns today; the four existing cases keep their assertions with the calls list
  becoming `[("node", True), ("agent-browser", True), ("ripgrep", True), ("ffmpeg", True)]`. That is the
  relationship the launcher depends on — postinstall asks pm, by these names, as an explicit install — and the
  JSON-final-line and sandboxed-shim cases are unchanged. Killing mutation to record: drop `explicit=True` from
  one `pm.ensure` call — the calls-list assertion reds.
- `tests/hermes_cli/test_dep_ensure_downstream.py` (fork-only; four `ensure_git_bash` cases against the deleted
  module) is replaced by cases against the new `_ensure_git_bash` in `_downstream_cli`: POSIX no-op returns
  `pm.shell.bash()`; Windows resolves without installing when `pm.shell.bash()` answers; Windows falls back to
  `pm.ensure("git", explicit=True)` and re-resolves; Windows returns `None` when pm cannot provision. Same four
  guarantees, pm's names.
- `tests/tools/test_find_bash_windows.py` (fork-only): the one case importing `_resolve_windows_git_bash`
  (`test_wsl_stub_only_returns_none` in `TestFindWindowsGitBash`) loses its subject; the guarantee (System32
  stub rejected) is now upstream's `pm.shell.windows_bash_candidates` and is exercised by upstream's own tests,
  so the case is deleted — the sibling `test_find_bash_raises_on_wsl_stub_only` keeps pinning `_find_bash`
  through pm.
- The hermetic harness sets `HERMES_DISABLE_LAZY_INSTALLS`; no test in this set may reach a real `pm.ensure`,
  which the recorder monkeypatch guarantees. `tests/_downstream/hermes_cli_conftest/fences.py`'s
  agent-browser-probe fence names `hermes_cli.dep_ensure` in its `_AGENT_BROWSER_PROBE_BINDINGS` tuple; that
  entry must be removed or the autouse fixture reds on the missing module for every `tests/hermes_cli` test.

**Does the `dep_ensure` ledger row retire?** Yes — the file is gone; its "PR candidate (G2): `ensure_git_bash`
provisioning, git/git-bash dep checks, `-NoProfile -NonInteractive` + stdin DEVNULL for install.ps1" has no
upstream target left (pm replaced the install-script spawn entirely). Nothing of it is carried forward.

---

## 3. Every other conflicting file — owner, rule, one line

Legend. **owner:** `upstream` (a fork edit whose home is an upstream PR), `seam` (a fork seam the merge must
keep alive), `fork-test` (fork-authored test lines inside an upstream test file). **rule:** `theirs` = take
upstream's hunk, the fork's carry is superseded or dropped (and the ledger row retires or shrinks); `both` =
upstream's hunk plus the fork's ADDITIVE lines re-applied on top; `port` = upstream's change ported into the
fork-only file the seam lives in. A `theirs` on a Windows-carry test file is conditional on that file being green
on Windows afterwards; if it is red, the fork hunk is re-applied as `carry` with the PR number (the 2026-09-24
merge found three such files). The eleven fork PRs are all still OPEN and none is in `upstream/main`
(`gh pr view`, 2026-09-25) — nothing is dropped for having merged.

### 3.1 Production and workflow files (25)

| file | hunks | owner | rule |
|---|---|---|---|
| `.github/workflows/tests-os.yml` | 1 | upstream | `both` — upstream's new arm64 job; re-apply the `github.repository == 'NousResearch/hermes-agent' && … \|\| 'windows-latest'` runner expression on each Windows job (the fork's CI cannot use hosted 32-core runners). |
| `.github/workflows/tests.yml` | 1 | upstream | `both` — upstream's `HERMES_TEST_FILE_TIMEOUT: 600`; keep the fork's `HERMES_TEST_WORKERS` repository conditional. |
| `acp_adapter/server.py` | 1 | seam | `both` — upstream's import line (it no longer exports `HERMES_VERSION` from `acp_adapter.commands`; `git grep` finds no `HERMES_VERSION` left under `acp_adapter/` upstream, so the fork's use of it moves to `hermes_cli.__version__` or is dropped where it was only echoed) plus the fork's `from agent_runtime.acp_skills import SKILLS_CAPABILITY, SkillsInspectionMixin`. |
| `agent/image_routing.py` | 1 | upstream | `theirs` — upstream's `[\\/]` class recognises Windows drive paths, which is the fork's whole edit; ledger row retires (supersession). |
| `apps/desktop/src/app/settings/uninstall-section.test.tsx` | 1 | fork-test | `both` — upstream's `waitFor` import; add `describe` back to the vitest import for the fork's describe block (ledger: leaves with the git-history-warning PR). |
| `cli.py` | 1 | upstream | `both` — upstream's `missing_is_expected` import plus the fork's `from hermes_cli.tirith_config import tirith_enabled` (carry stays until the tirith-config PR). |
| `hermes_cli/doctor_live.py` | 1 | upstream | `theirs` — upstream's probe is `_find_agent_browser(validate=False)` with no `HERMES_HOME` read at all, which is what the fork's call-time-home edit (G10) wanted; row retires. |
| `hermes_cli/doctor_state.py` | 1 | upstream | `both` — upstream's `check_legacy_desktop_checkout()` call; keep the fork's `HERMES_HOME = get_hermes_home()` in place of the module-level import (G10 carry stays). |
| `hermes_cli/gateway.py` | 1 (152 lines) | upstream | `theirs`, then re-point three fork callers — upstream's `_pm_runtime_venv_dir()` (`pm.environments.selected_venv`, the committed-environment contract) answers "the interpreter Hermes is installed into" that the fork's `resolve_managed_python` / `ManagedPythonUnavailable` were written for. Adopt: `agent_runtime/doctor_extensions.py`, `hermes_cli/gateway_windows.py` (the scheduled-task action's interpreter) and `hermes_cli/update_cmd_windows.py` call `_pm_runtime_venv_dir()` + `hermes_constants.venv_python_path`, treating `None` as the old exception. Ledger row shrinks by the resolver; the `getuid`/`pwd` guards and the home-receipt hunk stay `both`. **§5 Q4.** |
| `hermes_cli/main.py` | 1 (201 lines) | seam | `port` — upstream edited the profile-override block IN PLACE (`_looks_like_hermes_invocation`, `_looks_like_option_value`, `_scan_profile_flag`'s subcommand rule, the sudo-user fallback); the fork replaced that block with `hermes_cli/_profile_bootstrap.py`. Keep the fork's replacement shape; port every upstream change in the hunk into `_profile_bootstrap.py` (the 2026-09-24 merge's mechanic); `_apply_profile_override()` + the scratch-tmp export stay as the fork spells them. Nothing else in the file conflicts. |
| `hermes_cli/main_web_build.py` | 2 | upstream | hunk 1 `both`: upstream still defines `_sweep_stale_bytecode_if_checkout_changed` inline; keep the fork's one-line import from `hermes_cli/_bytecode_sweep.py` (the single-winner lock, G12 carry). hunk 2 `theirs`: upstream deleted `_source_tree_files` / `_hash_source_tree` / `_write_build_stamp` (no definition anywhere upstream now — pm owns builds), so the fork's loud-stamp-failure carry has no host and goes; row shrinks to the sweep import. |
| `hermes_cli/uninstall.py` | 3 | upstream | `theirs` on all three — upstream's `link.resolve()` states it "normalizes native Windows extended-path prefixes too", the class `_comparable_path` existed for; the PLUGIN-COMPAT `find_shell_configs` block is only referenced by `COMPAT_MANIFEST.md` (revert-scheduled, no importer) and goes with it. Row shrinks to the git-history warning. |
| `hermes_cli/update_cmd.py` | 1 | upstream | `both` — upstream's `target_ref` / release-tag branch; re-apply the three `guard_fork_history(...)` lines inside the non-release `else` (G17 carry stays: a release update never resets the branch, the guard is about `origin/<branch>` fast-forwards). |
| `hermes_cli/update_cmd_windows.py` | 1 (114 lines) | upstream | `theirs` — `5e4a2a3d24` removed "obsolete venv-holder handling"; the fork's `_clear_windows_venv_holders_or_exit`, `_reap_and_rescan`, `_terminate_leftover_gateways`, `_in_handoff_without_live_shim` and `_warn_legacy_console_gateway_task` (its `gateway_windows.task_action_is_console_less` has no upstream definition) have no update path left to run in. Row retires or shrinks to what a Windows update on the merged tree still needs (§5 Q4). |
| `plugins/platforms/feishu/adapter.py` | 1 | upstream | `theirs` — upstream reads `self._dedup_state_path`, assigned in `__init__` from `get_hermes_home()`: still frozen at construction, so the fork's per-call resolution is NOT superseded, but the hunk is one read line and the fork's `state_path` local no longer exists in upstream's shape. Take upstream; re-file the frozen-home finding as the `test_no_frozen_hermes_home` PR the row already names (carry, one line). |
| `pyproject.toml` | 2 | carry-permanent / upstream | hunk 1 `both`: upstream's multi-line `include` (adds `pm`, `pm.*`); add `"agent_runtime", "agent_runtime.*"` (ruled permanent). hunk 2 `both`: upstream's ruff `select` (drops `F821`, adds `TID251` + the `pm` banned-api table); re-add `"F821"` — the fork relies on it (**§5 Q5**). Plus the standing rule: the fork's `coverage` / `pytest-timeout` / `exclude-newer-package` / `--timeout=30` rows and every NEW upstream row; `uv.lock` re-locked over the merged file. |
| `scripts/install.ps1` | 5 (one of 1,946 lines) | upstream | `theirs` wholesale — upstream rewrote the installer for pm/bundles. The fork's four carries: (a) "install into the existing checkout / forks keep their origin" is superseded by upstream's `HERMES_REPO_URL` env door (`$RepoUrl = if ($env:HERMES_REPO_URL) …` and `git remote set-url origin` on reruns) — rule 10, adopt; (b) `-Ensure git`/`git-bash` retires with `dep_ensure` (§2.2); (c) `$script:ResolvedPathReport` and (d) segment-wise PATH dedup are re-applied ONLY if the launcher's installer consumes them — it does not (`mission_control_process_io.dart` bootstraps `uv` with astral's own `install.ps1` and never runs hermes's), so drop. Row retires. |
| `scripts/install.sh` | 2 | upstream | `theirs` wholesale — same rewrite; `REPO_URL="${HERMES_REPO_URL:-…}"` is the door for the fork's checkout carry; `resolve_install_layout` idempotence has no host left. Row retires. |
| `scripts/release.py` | 1 (2,084 lines) | upstream | `theirs` — upstream moved `LEGACY_AUTHOR_MAP` to `scripts/releases/authors_legacy.py` and reads `contributors/emails/` through `scripts/add_contributor.py`; the fork's `rglob` for `case-variants/` is re-checked against upstream's reader and re-applied there only if it still reads the flat directory. Row retires or moves to the new file. |
| `scripts/run_tests.sh` | 4 | seam | hunks 1–3 `theirs`: upstream's `_activation.sh` scheme honours an explicit `HERMES_PYTHON` that has pytest ("the Nix devShell's editable venv and CI's minimal installer lanes provide one on purpose") — that env var is the door the fork's shared-venv probe (`HERMES_TEST_VENV`, `~/.venvs/hermes-test`) was a second door beside. Adopt: the probe goes; `HERMES_PYTHON=C:/Users/beast/.venvs/hermes-test/Scripts/python.exe` is set in the lane briefs and the brain's setup note (**§5 Q6**). hunk 4 `both`: keep the fork's `PATHEXT` line beside upstream's MSVC toolchain loop. |
| `scripts/run_tests_parallel.py` | 1 | seam | `both` — keep the fork's `_adaptive_default_jobs(os.cpu_count())` default (P5 carry, one line). |
| `tools/environments/daytona.py` | 1 | upstream | `theirs` — upstream's `PurePosixPath(remote_path).parent` is the fork's `posixpath.dirname` fix; row retires. |
| `tools/environments/local.py` | 1 | upstream | `theirs` — bash discovery moved to `pm.shell.windows_bash_candidates` (same candidate order, same System32/WindowsApps stub exclusion, `HERMES_GIT_BASH_PATH` first); the fork's `_windows_bash_candidates` goes. The other fork hunks (`_msys_to_windows_path`, `_shell_arg_safe_path`, MSYS spellings) do not conflict and stay; row shrinks. |
| `tools/file_operations.py` | 1 | upstream | `theirs`, conditionally — upstream's `_escape_shell_arg(arg, translate_path=True)` adds the `translate_path=False` lane for regex patterns, which is the corruption class the fork routed around via `_shell_arg_safe_path`. Take upstream and run the fork's three pinning files (`tests/tools/test_path_form_characterization.py`, `tests/tools/test_local_env_windows_msys_downstream.py`, `tests/_downstream/tools_conftest.py`'s fixtures); a red re-applies the fork's four lines as the carry it is today. |
| `tools/tirith_security.py` | 1 | upstream | `both`, fork over upstream — upstream's `_verdict("allow")` on an unsupported platform is the silent allow the fork's `_unsupported_platform_result(cfg["tirith_fail_open"])` replaces (G18: fail-closed warning). Re-apply the fork's two lines; the carry is a replacement hunk and stays on the ratchet with its reason. |

### 3.2 Test files (28)

The pattern: 24 of the 28 are the fork's Windows PR carries (`up/win-*`, `#121218`–`#121226`) meeting upstream's
own Windows fixes for the same tests — `@pytest.mark.platforms(...)`, `USERPROFILE` set beside `HOME`,
`os.path.join` spellings, `write_bytes`. Upstream's version is `theirs` in every such hunk; the carried PR hunk
is gone from the tree; the PR stays open upstream untouched (it is a PR against upstream's tree, not ours) until
the supersession pass in §4 closes the ones whose files upstream fixed (**§5 Q7**).

| file | hunks | rule |
|---|---|---|
| `tests/agent/lsp/test_workspace.py`, `tests/agent/test_image_routing.py`, `tests/gateway/test_media_spaced_paths_and_history_dedupe.py` (hunk 1), `tests/gateway/test_platform_base.py` | 1 / 1 / 1 / 1 | `theirs` — upstream sets `USERPROFILE`; the fork's `tests/_home_env.point_home_at` stays for fork-only tests. |
| `tests/agent/test_file_safety_sandbox_mirror.py` (3), `tests/agent/test_save_url_image.py`, `tests/gateway/test_media_spaced_paths_and_history_dedupe.py` (hunk 2), `tests/hermes_cli/test_projects_db.py` (2), `tests/tools/test_checkpoint_manager.py` | | `theirs` — path-spelling assertions, upstream's `os.path.join` form. |
| `tests/agent/test_proxy_and_url_validation.py`, `tests/tools/test_skills_hub.py` (hunk 2) | 1 / 1 | `theirs` — the fork hunk is a comment only. |
| `tests/gateway/test_media_resend_dedup.py`, `tests/gateway/test_post_stream_media_delivery.py` | 1 / 1 | `theirs` — upstream's `str(img) in unquote(...)` substring form; if red on a path with a drive colon, re-apply the fork's round-trip assertion as the `up/win-path-spelling` carry. |
| `tests/hermes_cli/test_debug.py`, `tests/hermes_cli/test_diff_command.py`, `tests/tools/test_working_diff.py` | 1 each | `theirs` — upstream writes bytes / sets `core.autocrlf` itself (`up/win-line-endings` superseded for these files; `test_working_diff.py`'s upstream side uses `write_text` — red on Windows re-applies `write_bytes`). |
| `tests/hermes_cli/test_doctor_journal_modes.py` (3), `tests/hermes_cli/test_update_serve_generation_recovery.py` | | `theirs` — `platforms("posix")` marks replace the fork's `skipif`/`linux_only`. |
| `tests/hermes_cli/test_tui_resume_flow.py`, `tests/tools/test_mcp_tool.py` | 1 / 1 | `theirs` — upstream tolerates `\r\n` / upper-cases nothing (the `_build_safe_env` keys); if `test_mcp_tool.py` reds on `PROGRAMFILES` casing, re-apply the fork's `.upper()` normalisation (`up/win-env-var-case`). |
| `tests/tools/test_subprocess_home_isolation.py` | 1 | `both` — upstream ADDS two assertions; nothing of the fork's is in the hunk. |
| `tests/tools/test_base_environment.py` (2), `tests/tools/test_file_tools_live.py`, `tests/tools/test_file_ops_cwd_tracking.py`, `tests/tools/test_local_env_relative_cwd.py` | | `both` — upstream's new tests / imports plus the fork's helpers (`_bash_exe`, `_sh`, `_same_dir`, the `_find_bash` / `_msys_to_windows_path` imports) wherever a fork-authored test in the same file still calls them (`tests/_fork_scope.is_fork_authored` decides); an unused helper is not re-applied. |
| `tests/conftest.py` | 2 (308 + 550 lines) | `theirs` for the structure — upstream carved `_CREDENTIAL_NAMES` into `tests/_fixtures/env_filter.py` and `_live_system_guard` into `tests/_fixtures/live_system_guard.py`; the fork's lines inside those hunks are re-applied ONLY where `is_fork_authored` says so, into the fork-only root `conftest.py` (the ledger row says the fork half already loads from there). This is the hunk class that dropped six files' imports at the 2026-09-24 merge (`3ea8d47e10`): diff base→`origin/main` for the hunk range before taking theirs. |
| `tests/hermes_cli/test_cmd_update.py` | 1 | `both` — upstream's side is empty (it dropped the `_make_run_side_effect` helper); the fork's version models the history guard, which `update_cmd.py` keeps (§3.1). Keep the fork's helper if a surviving test in the file calls it, else drop. |
| `tests/hermes_cli/test_early_recovery.py` | 1 (121 lines) | `both` — upstream's new `test_bootstrap_and_pm_cli_work_without_site_packages` beside the fork's dotenv-shadow lifecycle block (fork-authored, `#57828`); both live. |
| `tests/scripts/test_run_tests_parallel.py` | 1 (101 lines) | `both` — upstream's receipt-dir tests plus the fork's node-id selector test (a fork runner feature the `_adaptive_default_jobs` carry sits beside). |
| `tests/tools/test_skills_hub.py` (hunk 1) | 1 | `theirs` — upstream rewrote the quarantine fixture without the seven `patch.object` targets. |

**What this does to the ledger and the ratchet.** Rows that retire outright: `agent/ssl_guard.py`,
`hermes_cli/dep_ensure.py`, `agent/image_routing.py`, `hermes_cli/doctor_live.py`, `tools/environments/daytona.py`,
`scripts/install.ps1`, `scripts/install.sh` — seven; rows that shrink: `agent/process_bootstrap.py` (the memo),
`hermes_cli/gateway.py` (the resolver), `hermes_cli/main_web_build.py`, `hermes_cli/uninstall.py`,
`hermes_cli/update_cmd_windows.py`, `tools/environments/local.py`, `tools/file_operations.py` (conditional),
`scripts/run_tests.sh`, `scripts/release.py`. The `[up-fp]` fixture (`files=200 deleted_lines=999 heavy=4` at
base `749220ef00`) is re-measured at the NEW base after `--refresh-manifest`; it must go down and the fixture
follows it (rule 2) — the exact numbers are the merge lane's to take, never this note's to predict.
