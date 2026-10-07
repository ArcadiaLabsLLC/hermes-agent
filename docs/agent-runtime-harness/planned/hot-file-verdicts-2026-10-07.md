# Job 2 hot-file verdicts — 2026-10-07

Phase A design only: this table commits alone before product edits. Parent batch review is required before extracts/drops. Job 3 remains LAST and is not started. User/Claude own final full validation and main landing; no full suite is authorized for this lane or parent.

## Exact refs and baseline

- origin/main and fork baseline: f076d86f380ecbc29e70fe8d3a3412bd815b8165 (Job 1 landed; ancestor check exit 0).
- upstream/main fetched: 865ba906c1a8d93de65839ee7af487204d42e873.
- merge-base: ee5f49b943f8a92165c598d23f52ab9b39c41ce7.
- Fresh branch refactor/hot-file-verdicts from origin/main; claim-only branch metadata/job2-claim-20261007, commit 21c64541250. Only Job 2 claimed, no product main landing.
- All registered worktrees inspected: primary untracked .claude/ and earlier grind-runtime logs/evidence/QA patch preserved; all other trees clean at inspection. Old runtime branch/worktree untouched.
- Inventory: 76 hunks across 14 files; verdicts:drop 1, extract 6, upstream 69. Extract is a proposed move, not completed. Only drop 10.01 proven. Six extract hunks form four proposed moves: runtime snapshot projection, ambient defaults, Windows PATH helper, gateway extension registration.
- Hunk identity command: git diff --unified=3 <merge-base> <fork-baseline> -- <14 paths below>. Each exact LF patch block has a SHA256. Imports/signatures/comments are inventoried too. Policy rows below apply to every referenced hunk, including mixed-hunk prerequisites.

## Footprint (no fixture edit)

Read-only python scripts/upstream_footprint.py exited 0: **[up-fp] files=184 deleted_lines=959 heavy=4**. Stored fixture: 176/883/4, base ee5f49b943. Discrepancy is pre-existing baseline evidence, not a passing ratchet test; do not silently raise fixture. Scoped 14 files: +337/-125. Phase A changes no product bytes and no measured footprint. After actual reductions measure whole-tree delta; lower only real falls and report existing excess honestly.

## Live PR evidence

gh pr view and fetched upstream/pr-124191 agree: [PR #124191](https://github.com/NousResearch/hermes-agent/pull/124191) OPEN, head f54abc0034373f98268d28e71bb1c218340ce1d6, updated 2026-10-07T02:00:36Z. Current source adds TIER_EXTRA between local/create, get_extra_skills_dirs and excluded_skill_dirs; current upstream lacks them. Job 1 explicitly deferred because baseline lacks tiered prerequisites. Prefer this design, not another root extraction. Parent must decide authorized history-preserving prerequisite integration without per-file copies or starting Job 3. PR author reports tests; those are not this phase proof.

Other OPEN current heads verified:

| PR | Head | Ledger candidate |
|---|---|---|
| [124210](https://github.com/NousResearch/hermes-agent/pull/124210) | fb0122d52f7950e0954973fa04e981269a55edc2 | native row/API hooks |
| [125261](https://github.com/NousResearch/hermes-agent/pull/125261) | 5c6e33a665ab9b3b13deb08961d1e6a554b9620f | Windows shell/PTY |
| [121643](https://github.com/NousResearch/hermes-agent/pull/121643) | acd91dfa42eaa5e02d47a04381d92eca672c4a42 | container POSIX paths |
| [124190](https://github.com/NousResearch/hermes-agent/pull/124190) | 5dfd9f30d27c2f7b230006517a10b7aa3275c691 | home ownership |

New PR candidates below are proposed ledger additions in later authorized CHANGE commits, not opened PRs. Existing attribution is not proof current PR covers every behavior.

## Decision policies

Runbook order for every hunk: check upstream replacement; then independent extraction; otherwise name upstream port/candidate. Acceptance paths are proposed focused selections, not results; verify exact nodes before running. Missing proof means no proven drop.

### visibility: upstream

Upstream evidence: Upstream has platform/environment/app predicates, no mission surface/root-node predicate or matching cache dimension. PR #124191 changes roots, not this policy.

Destination/seam/ledger: Keep signature/cache/filter seams; agent_runtime.skill_resolution owns policy. PR candidate public visibility predicate and snapshot metadata port; existing prompt_builder/skills_tool ledger hook rows. No second scanner.

Proof or missing prerequisite: `tests/agent/test_prompt_builder_downstream.py::TestBuildSkillsSystemPromptConditional::test_mission_chat_hides_root_node_only_skills`; tests/tools/test_skills_tool_downstream.py mission list case. Not run on upstream; no proven drop.

### snapshot: extract

Upstream evidence: Upstream _build_snapshot_entry has no metadata.hermes projection. Self-contained 17-line normalization can move.

Destination/seam/ledger: Move runtime projection into a public helper in agent_runtime.skill_resolution; one entry-field call remains. Preserve missing metadata/type defaults.

Proof or missing prerequisite: Mission-surface prompt case plus new snapshot-vs-scan parity. MOVE proof missing.

### ambient: extract

Upstream evidence: Upstream build_skills_system_prompt has no ambient mission scope. Five-line argument-default binding is independent.

Destination/seam/ledger: Public default resolver in agent_runtime.skill_resolution; one tuple-assignment call. Explicit false must differ from unset.

Proof or missing prerequisite: Mission-surface prompt case plus explicit override assertion. MOVE proof missing.

### context: upstream

Upstream evidence: Upstream build_context_files_prompt still chooses first truthy source with or; fork loads all.

Destination/seam/ledger: PR candidate context_files.load_all (#125257 ledger residue). No copying private loaders into fork; needs public loader policy.

Proof or missing prerequisite: `tests/agent/test_prompt_builder_downstream.py::TestBuildContextFilesPrompt::test_all_project_context_sources_load` and its override-order case. No differential proof.

### roots: upstream

Upstream evidence: Upstream has tiered project/local/create/external roots. PR #124191 adds writable TIER_EXTRA and excluded_skill_dirs. Fork baseline lacks tiered prerequisites.

Destination/seam/ledger: Prefer current PR #124191 over root extraction. Seed shared root/exclusions at call time through fork profile owner; no per-file upstream copies. Parent must resolve history-preserving release-policy integration first.

Proof or missing prerequisite: tests/agent/test_external_skills_downstream.py; tests/tools/test_skills_tool_downstream.py; PR tests/agent/test_skills_extra_dirs.py after integration. Need writable-vs-external ownership/profile-switch proof; none run here.

### posix: upstream

Upstream evidence: Current upstream lacks exact normalization at these lookup/cache/refusal sites; tier ownership changed.

Destination/seam/ledger: Generic Windows fix: PR #124191 for skill spelling; PR #121643 for credential cache paths. Existing ledger rows. One-line generic fix has no meaningful extract.

Proof or missing prerequisite: Skills downstream file or tests/tools/test_credential_files.py; add nested Windows cache-path case if missing. No upstream green.

### category: upstream

Upstream evidence: Tiered roots do not replace nested catalog category/identifier/tags contract.

Destination/seam/ledger: PR candidate catalog extension (#125257 ledger residue); keep upstream parsing sole owner.

Proof or missing prerequisite: tests/tools/test_skills_tool_downstream.py nested search-to-view case; add direct skills_list identifier/tags assertion, search alone insufficient. No upstream proof.

### resolver: upstream

Upstream evidence: Current upstream has tier-aware resolver; baseline fork replaced candidate walk with resolve_skill. Supersession plausible but support/collision ownership differs.

Destination/seam/ledger: Adopt canonical upstream resolver only after PR #124191 prerequisite; keep only missing behavior proven by tests. Existing ADOPT ledger row. Never extract a second resolver.

Proof or missing prerequisite: Need fork tests against upstream/PR for support Markdown, same-tier ambiguity, cross-tier shadowing, frontmatter/nested aliases. Missing proof means not proven drop.

### userrow: upstream

Upstream evidence: Upstream still appends a user row and stamps supplied metadata; no reuse_current_user_message/history-includes-current-user door.

Destination/seam/ledger: ROW-PR #124210. Keep signature/persistence-boundary threading. conversation_loop/session_persistence callers outside Job 2 require parent dependency review; no substitute fork staging owner.

Proof or missing prerequisite: tests/agent_runtime/test_mission_chat_turn_context.py; locate/add durable-row reuse and missing-user refusal assertions before execution. No upstream proof.

### secret: upstream

Upstream evidence: Upstream webhook uses Path read and atomic write; no credential-file backend.

Destination/seam/ledger: Already extracted agent_runtime.host_store.secret_files; retain minimal read/write seams. PR candidate pluggable read/write/unlink, existing webhook ledger. No global Path/open override.

Proof or missing prerequisite: tests/agent_runtime/test_host_store_seam.py and test_desktop_host_store.py; explicit bound/unbound webhook cases needed if absent. No upstream proof.

### slot: upstream

Upstream evidence: Upstream scrubbed child env lacks repo-slot overlay.

Destination/seam/ledger: Already extracted agent_runtime.workspace_slot_overlay; keep two-line call seam. PR candidate child-env transform port; local.py H5c ledger.

Proof or missing prerequisite: tests/agent_runtime/test_slot_env_overlay.py; command-visible overlay and no-slot no-op. Not run here.

### windows: extract

Upstream evidence: Upstream local.py lacks _augment_windows_system_path/_windows_system_path_dirs. Independent append-only Windows tooling helper.

Destination/seam/ledger: Move both helpers and separator constant to new fork-owned agent_runtime/windows_system_path.py. One import/call remains in _make_run_env; preserve OS/env/filesystem behavior. Generic PR #125261 retirement candidate.

Proof or missing prerequisite: Add/locate downstream tests: off-Windows no-op, case/separator dedup, precedence, missing dirs, constrained PATH. No MOVE proof yet.

### process: upstream

Upstream evidence: Upstream checkpoint follows get_hermes_home; wait ceiling reads TERMINAL_TIMEOUT with 180 fallback. Fork follows background ownership/scoped mission ceiling.

Destination/seam/ledger: Already extracted agent_runtime.process_notifications. HOME-PR #124190 path; scoped wait policy PR candidate (#125256 residue). Never set global 600 because foreground/kanban share the variable.

Proof or missing prerequisite: tests/gateway/test_background_process_notifications_downstream.py, test_multiplex_process_memo_scope.py; tests/tools/test_process_wait_lane_clamp.py. No upstream proof.

### eof: upstream

Upstream evidence: Upstream still uses pty.sendeof unconditionally; fork Windows Ctrl-Z+CRLF.

Destination/seam/ledger: PR #125261 generic Windows PTY EOF; process_registry ledger. One-line correction stays.

Proof or missing prerequisite: Add/locate fork-owned Windows/non-Windows EOF spy and native Windows PTY behavior proof. No upstream green.

### eviction: drop

Upstream evidence: Upstream _stamp_event retains seq and truncation counters on FIFO eviction (#100122). Same fork invariant now implemented.

Destination/seam/ledger: Later authorized integration takes upstream eviction implementation only. Keep separate checkpoint/forget_session hunk. No per-file upstream replacement on release baseline.

Proof or missing prerequisite: Exact unchanged fork test against exact upstream module:1 passed; killing reset mutation1 failed assert 0 == 3. Receipt below.

### replay: upstream

Upstream evidence: Upstream has separate events_since/latest_seq/is_truncated, no checkpoint or forget_session; newer frozen-byte ring differs from baseline dict ring.

Destination/seam/ledger: PR candidate atomic replay checkpoint and explicit owner-retirement cleanup. Existing replay ledger. Keep one lock/cache owner; cannot paste current fork checkpoint unchanged onto byte ring.

Proof or missing prerequisite: Eviction test does not cover APIs: add concurrent coherent checkpoint and cleanup byte-accounting tests. No upstream proof.

### recovery: upstream

Upstream evidence: Upstream lacks native fenced interrupt/observe-only attach/exact retirement at these sites. Existing resume may reopen/repair durable state.

Destination/seam/ledger: Keep minimal seams into existing fork-only tui_gateway/session_execution.py, session_recovery.py, session_retirement.py, recovery_history.py (ledger-listed). PR candidate native control/observe-only ports. RLock changes need reentrant-control proof.

Proof or missing prerequisite: tests/tui_gateway/test_native_execution_fence.py, test_native_recovery_dispatch.py, test_native_recovery_snapshot.py, test_native_session_retirement.py. Narrow touched nodes after design. Not run here.

### metadata: upstream

Upstream evidence: Upstream submit writer lacks execution display_metadata forwarding.

Destination/seam/ledger: PR candidate submit-row metadata input. Existing session_workdir ledger. Keep sole durable writer; no parallel transcript journal.

Proof or missing prerequisite: Native fence/recovery files; add exact submitted metadata roundtrip and no-native no-op if absent. No upstream proof.

### optional: upstream

Upstream evidence: Upstream eagerly imports local/contracts/connectors; no phone optional-module/registry door.

Destination/seam/ledger: Already extracted agent_runtime.loop_tool_lifecycles and tui_gateway.contract_seam. PR candidate optional module/registry port; phone ledger rows. Preserve unrelated nested ImportError propagation.

Proof or missing prerequisite: tests/agent_runtime/test_embedded_phone_session.py; tests/agent/transports/test_sdk_free_phone_imports.py. Add nested ImportError case if missing. Not run here.

### registration: extract

Upstream evidence: Upstream server registration lacks fork PDF/native recovery/retirement methods. Combined hunk includes connector omission and optional PDF dispatch.

Destination/seam/ledger: New fork-owned agent_runtime/gateway_extensions.py registers existing fork owners and handles explicitly omitted modules; one import/call in server. Preserve module order, globals, _CONNECTOR_RPC_METHODS and unrelated ImportError failures; do not move upstream method ownership.

Proof or missing prerequisite: Embedded phone/import, native recovery/retirement and actual PDF dispatch cases; missing exact registration-order/error-discrimination proof before MOVE.

### identity: upstream

Upstream evidence: Upstream exposes _live_session_identity but session_info still computes mirror/pending identity separately; latest fallback uses _lazy_info_route. Helper existence alone proves no drop.

Destination/seam/ledger: PR candidate unify live/resume model/provider projection; server shared-provider ledger. Retain upstream identity owner, no new precedence scheme.

Proof or missing prerequisite: tests/tui_gateway/test_local_model_session_identity.py; tests/gateway/test_session_identity_restore.py. Compare current upstream pending/custom/provider paths first; no proven drop.

### thread: upstream

Upstream evidence: Upstream agent build still creates threading.Thread directly.

Destination/seam/ledger: Keep public spawn_context_thread call; PR candidate gateway context propagation; server shared-provider ledger.

Proof or missing prerequisite: tests/gateway/test_session_context_inheritance.py, shared-provider configuration cases. Need actual worker context receipt; not run here.

### ui: upstream

Upstream evidence: Upstream lifecycle UI set lacks skill_view.

Destination/seam/ledger: PR candidate lifecycle observer/configurable set; existing server held skill_view ledger. One set entry not extracted.

Proof or missing prerequisite: Locate/add actual skill_view start/end event assertion through native admission. No proof yet.

### mcp: upstream

Upstream evidence: Upstream session_info calls get_mcp_status without mcp_client_enabled guard.

Destination/seam/ledger: Keep minimal gate; PR candidate disabled-client inspection no-op. No fork discovery owner.

Proof or missing prerequisite: Locate/add disabled session.info proves discovery never called plus enabled parity. No proof yet.

### factory: upstream

Upstream evidence: Upstream constructs AIAgent directly and schedules prewarm before native Launcher binding.

Destination/seam/ledger: Already extracted worker_app_functions remains owner; keep create_agent and admitted-turn deferral. PR candidate client-tool factory/context hook in server ledger. Compute-isolation deferral separately qualified.

Proof or missing prerequisite: tests/agent_runtime/test_native_app_functions.py, test_launcher_app_functions.py; add compute-profile prewarm no-local-build case if absent. Not run here.

## Complete hunk table

Diff coordinates identify immutable hunk content; implementation decisions cite symbols. Each policy supplies evidence, destination, PR/ledger and missing proof for every assigned row.

### agent/prompt_builder.py

Baseline +39/-7; upstream source SHA-256: d109f9c08441dcc03cc3d7eb52e489cc0de7a68b25007ec2bcb460b0506f95dd; fork source SHA-256: 2868bbd1a0b7b637a47efc3b839271109096762e89c4b7ae18cb008a1f5150ca.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 01.01 | `@@ -28,6 +28,7 @@ from agent.skill_utils import (`<br>`848cb8f00801404ab6a5efbd6e783f5e54a896b2aa210fb3fe42ab75da510913` | from agent_runtime.skill_resolution import current_skill_runtime_context, skill_frontmatter_runtime_compatibility | **upstream** / visibility |
| 01.02 | `@@ -1220,10 +1221,27 @@ def _build_snapshot_entry(skill_file: Path, skills_dir: Path, frontmatter: dict,`<br>`2a864ccfac1e658bf404500adec024169c2d836df335ddd7ef7d0eb685ff05ac` | metadata = frontmatter.get("metadata") if isinstance(frontmatter, dict) else {} / hermes = metadata.get("hermes") if isinstance(metadata, dict) else {} / runtime = {} / if isinstance(hermes, dict): / surfaces = | **extract** / snapshot |
| 01.03 | `@@ -1294,6 +1312,7 @@ def _current_session_platform_hint() -> str:`<br>`b4a5f1edc09747ab4936bc82a7c4393675402658075c96f03f14df726601aa73` | skill_surface: str &#124; None = None, skill_root_node_mode: bool &#124; None = None, | **upstream** / visibility |
| 01.04 | `@@ -1302,6 +1321,11 @@ def build_skills_system_prompt(`<br>`3fd7faa5e2c81c7219f576fdef2a2d7f422489be33649b4b6ab60a964a8a30b9` | ambient_surface, ambient_mode = current_skill_runtime_context() / if skill_surface is None: / skill_surface = ambient_surface / if skill_root_node_mode is None: / skill_root_node_mode = ambient_mode | **extract** / ambient |
| 01.05 | `@@ -1316,7 +1340,8 @@ def build_skills_system_prompt(`<br>`fde446412b48df88cddf49e848e54885d14997fc60ffcb05bd072d977571b8a2` | skills_dir, external_dirs, available_tools, available_toolsets, compact_categories, project_dirs, / skill_surface, bool(skill_root_node_mode)) | **upstream** / visibility |
| 01.06 | `@@ -1350,7 +1375,7 @@ def _collect_extra_skills(`<br>`878a84426d11e5d824455ab9b0ecfff559cb5edd64164f75b0b6be22f2dcdaec` | if not entry or fm_name in claimed or hides(fm_name, entry["skill_name"], extract_skill_conditions(frontmatter), entry.get("runtime")): | **upstream** / visibility |
| 01.07 | `@@ -1444,6 +1469,7 @@ def _build_skills_system_prompt_inner(`<br>`f46c737498ca8a6023b9e587ffec809a6e88fd6bedcff049d3ec66ecb88d5647` | skill_surface: str &#124; None = None, skill_root_node_mode: bool = False, | **upstream** / visibility |
| 01.08 | `@@ -1454,6 +1480,7 @@ def _build_skills_system_prompt_inner(`<br>`d2f24be94c0d9461f75e328dd6e119166dff80fe16556d3dde6a8a4fe76f2c6e` | skill_surface or "", bool(skill_root_node_mode), | **upstream** / visibility |
| 01.09 | `@@ -1466,8 +1493,13 @@ def _build_skills_system_prompt_inner(`<br>`5a556092643f842bc68b2dbf4172eca7afe0f640a4bcd38b1d0d140aa5f32559` | def hides(frontmatter_name: str, skill_name: str, conditions: dict, runtime: dict &#124; None = None) -> bool: / if skill_surface and not skill_frontmatter_runtime_compatibility( / {"metadata": {"hermes": runtime or | **upstream** / visibility |
| 01.10 | `@@ -1487,7 +1519,7 @@ def _build_skills_system_prompt_inner(`<br>`117ec01cbfcbcb104880176960f94304ccad50879ce3e3191eb98c4f4ce01d61` | if is_compatible and not hides(_entry_name(entry), entry.get("skill_name") or "", entry.get("conditions") or {}, entry.get("runtime")) | **upstream** / visibility |
| 01.11 | `@@ -1768,7 +1800,7 @@ def build_context_files_prompt(`<br>`a6ba78b79db31f0431caeaa3518d4e26d560f423c60c8cc530208d2119e0701a` | All present project context sources load in this deterministic order: .hermes.md/HERMES.md (walk to git root) → | **upstream** / context |
| 01.12 | `@@ -1780,8 +1812,8 @@ def build_context_files_prompt(`<br>`cf89ad3e171fb80433d57aabf8e1c5be4d26361e91e9297943da36631dc602b2` | sections = [_load_hermes_md(cwd_path, context_length), _load_agents_md(cwd_path, context_length), / _load_claude_md(cwd_path, context_length), _load_cursorrules(cwd_path, context_length)] | **upstream** / context |

### agent/skill_utils.py

Baseline +9/-4; upstream source SHA-256: 5e19ee7c502c67b70256207d90d186ef6a4da631dff075669f6c6a827ac73633; fork source SHA-256: fdf8e5edc1bee5c28618bf7e16f190911e14dd75c4d07e99b3e97d3a69d1fe5c.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 02.01 | `@@ -14,6 +14,7 @@ from hermes_constants import (`<br>`06c91c68116010354214eb66cfd6d391f6b6aad48c123d00d65d80dc717d51d3` | from agent_runtime.profile_home import get_shared_skills_dir | **upstream** / roots |
| 02.02 | `@@ -21,6 +22,7 @@ PLATFORM_MAP = {"macos": "darwin", "linux": "linux", "windows": "win32"}`<br>`4aca7ad1f1f2b952bd4db7aa84970bc0ce84c1711e1ae1bf539d2c64e5b65712` | ".realm_inbox", ".provenance", | **upstream** / roots |
| 02.03 | `@@ -419,8 +421,11 @@ def get_all_skills_dirs() -> List[Path]:`<br>`3cd05d1bac42c77fcf50b2d15986416568cc5bf44a40ac6dbdee3f2a76538079` | shared = get_shared_skills_dir() / if shared.expanduser() != dirs[0].expanduser(): / dirs.append(shared) / if create_dir is not None and create_dir.is_dir() and create_dir not in dirs: | **upstream** / roots |
| 02.04 | `@@ -603,7 +608,7 @@ def normalize_skill_lookup_name(identifier: str) -> str:`<br>`b85bbde3169cdad0291e12b8db376d64434a372dab8cf68fb90ea3fd82709a35` | for getter in (get_project_skills_dirs, get_all_skills_dirs): | **upstream** / roots |
| 02.05 | `@@ -613,9 +618,9 @@ def normalize_skill_lookup_name(identifier: str) -> str:`<br>`246b2f73fac342ba9264f40003e3bf7dae29ac66c5b224965c1f3d56c3306c66` | return identifier_path.relative_to(root).as_posix() / return identifier_path.resolve().relative_to(primary_root.resolve()).as_posix() | **upstream** / posix |

### agent/turn_context.py

Baseline +20/-8; upstream source SHA-256: 1db15cc5ee39ab3dafe9f646680f8468dd2bd6401bf4123e891697bf8206efba; fork source SHA-256: 367f081a7b68dbc8dc716f6f8436c9fe2408df454b10365d01fc8759e127aaa7.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 03.01 | `@@ -627,6 +627,7 @@ def _stage_turn_user_message(`<br>`bdd0b7ff5fcd54e6a5c839008b6461127066de867d08577dc2de0bdb9a5e0329` | *, reuse_current_user_message: bool = False, | **upstream** / userrow |
| 03.02 | `@@ -653,10 +654,11 @@ def _stage_turn_user_message(`<br>`b11a5350959d1625da63467e7fed2ade7facc21aec12ca5409365287e0386a2e` | if not reuse_current_user_message: / if persist_user_display_kind: / user_msg["display_kind"] = persist_user_display_kind / if persist_user_display_metadata: / user_msg["display_metadata"] = persist_user_displa | **upstream** / userrow |
| 03.03 | `@@ -990,7 +992,7 @@ def build_turn_context(`<br>`f2671bcc5be94c841fc0b6f7466bde789ac3215fdfd1756ab1126a6eb2907cda` | set_current_write_origin, ra, moa_active: bool=False, reuse_current_user_message: bool=False, | **upstream** / userrow |
| 03.04 | `@@ -1061,14 +1063,24 @@ def build_turn_context(`<br>`c9c165f2c38c8cbad182d6472967c47296cc57d27a99323f83029b436f477c60` | reuse_current_user_message=reuse_current_user_message, / if reuse_current_user_message: / current_turn_user_idx = next( / (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"), -1,  | **upstream** / userrow |

### agent/turn_facade.py

Baseline +2/-0; upstream source SHA-256: 5797b456f1ac86fb099c4f20c39a2652b63c72d0c9098c9e72ad66cd47ee63ae; fork source SHA-256: 41c593893fefeb29ec81568753490f2937ca042ce772d8050a5892320583bf8f.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 04.01 | `@@ -28,6 +28,7 @@ class TurnFacadeMixin:`<br>`cae6ef948c8d73ba275f834a4de373b72756caa76566062d319b787569f9aebd` | reuse_current_user_message: bool = False, | **upstream** / userrow |
| 04.02 | `@@ -151,6 +152,7 @@ class TurnFacadeMixin:`<br>`77f6613413bd921264bee3d5533ee232f9c507e45e1f9fbd872df4bcd863c67b` | reuse_current_user_message=reuse_current_user_message, | **upstream** / userrow |

### hermes_cli/webhook.py

Baseline +5/-0; upstream source SHA-256: eae7825800afc86183435d247de6f0f9b3fdb4fb8b0f673a100ebc67eb4d5093; fork source SHA-256: 1fdbd08f84d9368c1219cd01023c957cc27d00867c4f43e01509836183c948aa.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 05.01 | `@@ -26,6 +26,8 @@ def _subscriptions_path() -> Path:`<br>`527bc83a850d1e698d0e4ab2990ffcc96f08e5a67bf3e4487a622c435286530e` | from agent_runtime.host_store import secret_files as _host_secrets  # fork seam: phone credentials seam / path = _host_secrets.view(path) | **upstream** / secret |
| 05.02 | `@@ -38,6 +40,9 @@ def _load_subscriptions() -> Dict[str, dict]:`<br>`c90035273545018fc3eea0038d60d2cceb5cc4652d1518466392ef943801cb16` | from agent_runtime.host_store import secret_files as _host_secrets  # fork seam: phone credentials seam / if _host_secrets.bound(): / return _host_secrets.write_json(_subscriptions_path(), subs) | **upstream** / secret |

### tools/credential_files.py

Baseline +1/-1; upstream source SHA-256: 181e6bd4cab6437fdd7156029f8cf896838247a14e332a740f79558116b6c345; fork source SHA-256: ef2be3b7fc2611cc2a9ecb4f0e36a302e17a26d4b5ba458642f915b5db78ec13.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 06.01 | `@@ -381,7 +381,7 @@ def to_agent_visible_cache_path(host_path: str, container_base: str = "/root/.he`<br>`4d1e0db1091998065f2e8ba5f30fdad74a932287cc3680c29879ea3f0176c0c8` | return [_mount(item, f"{root}/{item.relative_to(host_dir).as_posix()}") | **upstream** / posix |

### tools/environments/local.py

Baseline +69/-1; upstream source SHA-256: d96c53a2755e0afc6566e790ae9489a825c4d790c51bfcc258c78aafc2a47a26; fork source SHA-256: e87dbc690e135e13f592247140c72df831eb309587d0d86e94baba95b0ccc0f7.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 07.01 | `@@ -304,6 +304,8 @@ def _scrubbed_env(parts, plugin_strip: frozenset, fix_path) -> dict:`<br>`786006a52561dbaec5c1a5f9053cb7090e1e7599d320440052cbe6ef1a114413` | from agent_runtime.workspace_slot_overlay import apply_slot_env_overlay  # fork seam: repo-slot env (build plan H5c) / out = apply_slot_env_overlay(out) | **upstream** / slot |
| 07.02 | `@@ -685,7 +687,7 @@ def _make_run_env(env: dict) -> dict:`<br>`9b2215588fa0051288122dcf7e7cb10efb1a654e1c0a706ee34574a935355174` | lambda p: _augment_windows_system_path(_prepend_git_bash_dirs(_append_missing_sane_path_entries(p)))) | **extract** / windows |
| 07.03 | `@@ -1006,3 +1008,69 @@ class LocalEnvironment(BaseEnvironment):`<br>`9a7494336435a0df49290918c204996f79618427e48f9ea5373488e34c3dda21` | def _windows_system_path_dirs() -> "list[str]": / """Windows dirs that host the native command tooling the agent may shell / out to from its bash terminal — cmd.exe, powershell.exe (Windows / PowerShell | **extract** / windows |

### tools/process_registry.py

Baseline +4/-6; upstream source SHA-256: 4dacd3f6753d7b81e4ab338f7612624ec1f11c074cc969db49024a967a3b625e; fork source SHA-256: 31cdafd237b5823b8b409fbc08190790483e465aec7c8935707f7d61f4b2733c.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 08.01 | `@@ -34,6 +34,7 @@ from hermes_cli.config import get_hermes_home`<br>`02b7e311808509f483aa2087e2d5ad4848460cc788a211c2ecbf86906d801ea0` | from agent_runtime.process_notifications import checkpoint_path, wait_ceiling_seconds | **upstream** / process |
| 08.02 | `@@ -48,7 +49,7 @@ def _checkpoint_path() -> Path:`<br>`b52580045260102af189794ff6348c871e3e428bdbabfa69d0a5c6539d0607e9` | return CHECKPOINT_PATH if CHECKPOINT_PATH != _CHECKPOINT_PATH_AT_IMPORT else checkpoint_path() | **upstream** / process |
| 08.03 | `@@ -2150,10 +2151,7 @@ class ProcessRegistry(ProcessCheckpointMixin):`<br>`93e501b44e32850f6a5c79ec744510c4fb8bf621c21b5512bc76ff541573c8bd` | max_timeout = wait_ceiling_seconds() | **upstream** / process |
| 08.04 | `@@ -2421,7 +2419,7 @@ class ProcessRegistry(ProcessCheckpointMixin):`<br>`e3e402f85ef127c501cd54729449a82bcbaaeba812a44786c4c3ff9b6849f2b7` | session_id, lambda pty: pty.write("\x1a\r\n") if _IS_WINDOWS else pty.sendeof(), lambda stdin: stdin.close(), {"status": "ok", "message": msg}) | **upstream** / eof |

### tools/skills_tool.py

Baseline +53/-68; upstream source SHA-256: 7120cd8f7986f76813e1e9f243c2ed1358b27623d31bbd754821409f71d8de5c; fork source SHA-256: 3138639bd7154d5d720d7113458297afbd1ee26604a5a485defbb67e1563199a.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 09.01 | `@@ -29,6 +29,11 @@ from tools.skills_tool_dedup import (  # noqa: F401`<br>`fd4b742f8b04f85598f8849a6571512d75b397cf7dcbdb79b394cf9b919f2c7f` | from agent.skill_utils import get_all_skills_dirs / from agent_runtime.skill_resolution import ( / current_skill_runtime_context, resolve_skill, skill_frontmatter_runtime_compatibility, / ) | **upstream** / visibility + roots + resolver (mixed import) |
| 09.02 | `@@ -124,16 +129,25 @@ def check_skills_requirements() -> bool:`<br>`86c0bd5c6db568a5ae838216ea11a97d5b7e847ea7d1f7da7e5c9b092deb4ed1` | """ / Extract category from skill path based on directory structure. / For paths like: ~/.hermes/skills/mlops/axolotl/SKILL.md -> "mlops" / and ~/.hermes/skills/foundations/runtime/foo/SKILL.md -> / "foundation | **upstream** / category |
| 09.03 | `@@ -176,8 +190,7 @@ def _skill_search_dirs() -> Tuple[list, list, Path]:`<br>`a7d77bd59747ac915726447d28d74be944c5d255bdf7091711c20b609c7170e1` | all_dirs = project_dirs + [d for d in _runtime_skill_dirs() if d.exists()] | **upstream** / roots |
| 09.04 | `@@ -188,7 +201,8 @@ def _find_all_skills(*, skip_disabled: bool = False) -> List[Dict[str, Any]]:`<br>`7ebf82319080e1e612e3f7c9f187a188a3c5d928f397d485d8006e01bcf790e3` | active_surface, root_node_mode = current_skill_runtime_context() / signature = (_skills_scan_signature(dirs_to_scan, disabled), active_surface, root_node_mode) | **upstream** / visibility |
| 09.05 | `@@ -206,6 +220,9 @@ def _find_all_skills(*, skip_disabled: bool = False) -> List[Dict[str, Any]]:`<br>`2355bc191ef07d0bd0fe8b14e320f19bcc43418508604cbd6f1a0f9bac797e2e` | if active_surface and not skill_frontmatter_runtime_compatibility( / frontmatter, surface=active_surface, root_node_mode=root_node_mode).get("compatible"): / continue | **upstream** / visibility |
| 09.06 | `@@ -214,7 +231,9 @@ def _find_all_skills(*, skip_disabled: bool = False) -> List[Dict[str, Any]]:`<br>`a4de62060c4e0e6dbf5d0ef7703f9cf5aa5953c34c153ab9cf00d6edfc8729c5` | category = _get_category_from_path(skill_md) / skills.append({"identifier": f"{category}/{name}" if category else name, / "tags": _parse_tags(frontmatter.get("tags")), "name": name, "description": _truncate_des | **upstream** / category |
| 09.07 | `@@ -313,59 +332,9 @@ def _under_any(path: Path, dirs) -> bool:`<br>`d1acb079e8fe73dbbb06ec9971a3fa3b40b53b695b1d1d20cb2634b49d4f7cae` | resolution = resolve_skill(name, roots=all_dirs, categorized_identifier=local_category_name) / return [(candidate.skill_dir, candidate.skill_md) for candidate in resolution.candidates] | **upstream** / resolver |
| 09.08 | `@@ -524,10 +493,12 @@ def _locate_skill(name: str, local_category_name: Optional[str], project_dirs: l`<br>`89fb34a8ea15d398bd3f5d973269455b584da2a359538ad6317e904f3fdfd53b` | "; ".join(smd.as_posix() for _sd, smd in ranked[1:])) / # Fork: POSIX spelling keeps the refusal message identical on Windows and POSIX, / # which the fork's skill-path assertions depend on. / paths = [smd.as_p | **upstream** / posix |
| 09.09 | `@@ -617,7 +588,7 @@ def skill_view(`<br>`30659296316618a203094fcefb27435246f443cbe0d9aa4d93e904f6ed9a086b` | rel_path = skill_md.relative_to(active_skills_dir).as_posix() | **upstream** / posix |
| 09.10 | `@@ -751,3 +722,17 @@ def _skill_view_with_bump(args, **kw):`<br>`89597e7b81b04988d9e23b829a7e9c221dab52faea5b4fd9e973d247bc9d0bde` | def _runtime_skill_dirs() -> List[Path]: / """Canonical registry with the patchable active profile root first.""" / dirs = [_skills_dir(), *get_all_skills_dirs()[1:]] / result: List[Path] = [] / seen: set[Path] | **upstream** / roots |

### tui_gateway/event_replay.py

Baseline +21/-2; upstream source SHA-256: 1d0e6de6bec2955dc514d1609e0ac9f688537c376816f019dfea7a73a11270ff; fork source SHA-256: d19c548eac536b23fd76cc7a0a90aab2c7350cef3920b464c97ab9f1fc38840f.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 10.01 | `@@ -74,8 +74,8 @@ def _stamp_event(obj: dict) -> None:`<br>`82d9e2d3593c39316a4df7ef1eb8a9f52472b9682acf05392a95011239b96132` | # Cache eviction is not session retirement or a new sequence epoch. / _replay_evicted_through[oldest_sid] = _replay_next_seq[oldest_sid] | **drop** / eviction |
| 10.02 | `@@ -132,6 +132,25 @@ def reset_replay_state() -> None:`<br>`d234ff22d80e7a3a6fbcf1bca1c781fd87f3f3504a37a62c3458e888a0e4ba5f` | def forget_session(sid: str) -> None: / """The session owner calls this only after retirement; live counters outlast rings.""" / with _replay_lock: / global _replay_total_bytes / _replay_buffers.pop(sid, None)  | **upstream** / replay |

### tui_gateway/methods_session.py

Baseline +23/-7; upstream source SHA-256: 4929e1621444054927d8024a03c3ce7a3fc92377268af651bb37a16e86af46c4; fork source SHA-256: d15707b4c7e306bc8fa3fd6ec3c51738e06ee8fb3524b8770bce35f55660fbf4.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 11.01 | `@@ -399,7 +399,7 @@ def _create_session(rid, params: dict, *, copy_parent_history: bool = False) ->`<br>`ad9aa905c7f0e8cbc8c9e25fddfe229cf82cd27c7bb43c6ae1d3083729d96cc1` | "history": history, "history_lock": threading.RLock(), "history_version": 0, "image_counter": 0, | **upstream** / recovery |
| 11.02 | `@@ -601,7 +601,7 @@ class _Resume:`<br>`8bbd8295b3ea972f564e56806b47cd098295bcaea1002751e7034d3c1102e937` | self.lazy, self.defer_history = _flag(params, "lazy") or _flag(params, "observe_only"), _flag(params, "defer_history") | **upstream** / recovery |
| 11.03 | `@@ -627,6 +627,7 @@ class _Resume:`<br>`d6fb237dbcc100349b5e17223f092f5bd96fa659a8a2532b238afe3d7965f6b5` | record["observe_only"] = _flag(self.params, "observe_only") | **upstream** / recovery |
| 11.04 | `@@ -843,9 +844,11 @@ def _resume_lazy(ctx: _Resume) -> dict:`<br>`7977066d20b1845fb21a859682b7632e779d4a2c8cb8f3813e0d88bd8559d78a` | observing = _flag(ctx.params, "observe_only") / if not observing: / ctx.db.reopen_session(ctx.target) / history = ctx.child_history(repair=not observing) | **upstream** / recovery |
| 11.05 | `@@ -2242,6 +2245,13 @@ def _resume_wake_after_interrupt() -> None:`<br>`2fb6b20fc221b7d88322ed4c3dbf53365c602b691b2c44bf67b7da36f2843db6` | if expected := _str_param(params, "expected_execution_id"): / session, err = _sess_nowait(params, rid) / if err: / return err / from tui_gateway.session_execution import interrupt / applied = interrupt(str(para | **upstream** / recovery |
| 11.06 | `@@ -2462,17 +2472,23 @@ def _(rid, params: dict, session: dict) -> dict:`<br>`875e05901cbc292bc476cc59ef1d1b9db65a0fe244011a0142c76513da5efa31` | session = _sessions.get(sid) / if session and session.get("_compute_host_active") and _session_uses_compute_host(session): / try: / reply = _get_compute_host_supervisor().observe(sid, "session.events.since", pa | **upstream** / recovery |

### tui_gateway/server.py

Baseline +67/-15; upstream source SHA-256: 03b0f70c3652fe0a0be03898c27737ecbf07373b56619b684dae21aaf4094ec8; fork source SHA-256: 472453bed4079ab7ac7661b55a3495bdf122edf1c98cb4e8c154a15e990ff6ff.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 12.01 | `@@ -28,7 +28,12 @@ from hermes_constants import (`<br>`d69165dcdff5dc983c6e6d969196cb5c3e3c53f7408b0b316fd41600f48064f2` | try: / from tools.environments.local import hermes_subprocess_env / except ImportError:  # fork seam: phone wheel — the local execution environment is not shipped / from agent_runtime.loop_tool_lifecycles impor | **upstream** / optional |
| 12.02 | `@@ -37,7 +42,8 @@ from agent.conversation_loop import INTERRUPT_WAITING_FOR_MODEL_PREFIX  # noqa:`<br>`9a0b535d4bc92b623e0190e98c3816f01184d96b4f33f0621225dcdf83af5b95` | # Fork seam (embedded Hermes): the registry the profile selects (pydantic, or the generated catalog). / from tui_gateway.contract_seam import registry as _contracts | **upstream** / optional |
| 12.03 | `@@ -178,6 +184,9 @@ _LONG_HANDLERS = frozenset({`<br>`f10f2077357e324415b411a1d43ee9409d893d1d2fe1fd4e5ed0b2b108241399` | # Recovery, retirement and answers can await the compute owner. Stop must remain readable. / "session.recover", "session.recovery.history", "session.recovery.inflight", / "session.events.since", "session.retire | **upstream** / recovery |
| 12.04 | `@@ -649,6 +658,11 @@ def _default_session_cwd() -> str:`<br>`685498ecab8b3e3880c0688e6db667475c7d086b6f76c70c6befef78327fc998` | from tui_gateway.session_execution import publish / return publish(_sessions, obj, _write_json_frame) / def _write_json_frame(obj: dict) -> bool: | **upstream** / recovery |
| 12.05 | `@@ -1166,7 +1180,8 @@ def _start_agent_build(sid: str, session: dict) -> None:`<br>`ff117fc2eb7b8ac758d8c41a2ab19256a5cfae3bb1d5bdb0a358bd2a55070aae` | from agent.memory_provider import spawn_context_thread / build_thread = spawn_context_thread(_build, name="tui-agent-build") | **upstream** / thread |
| 12.06 | `@@ -2016,6 +2031,7 @@ _TOOL_LIFECYCLE_UI_TOOLS = frozenset({`<br>`40e01f68db043ab453e0b39059a0bbbe45e6f3470f2f94c7568b9052ea184a00` | "skill_view",  # fork 11c94aca7c: native conversation admission renders it | **upstream** / ui |
| 12.07 | `@@ -2241,15 +2257,13 @@ def _session_info(agent, session: dict &#124; None = None) -> dict:`<br>`910b24d87bab39fa7a27b69e219cf3c2b81c6caefec2b1dbda165a4741ca2c46` | model, provider = _live_session_identity({**sess, "agent": agent}) | **upstream** / identity |
| 12.08 | `@@ -2293,8 +2307,10 @@ def _session_info(agent, session: dict &#124; None = None) -> dict:`<br>`2281b39d74cf4123e622a9aa0e62616bb7ab03c125ca3c73c50614964b22f74b` | from tools.mcp_tool_common import mcp_client_enabled  # fork seam: mcp.client off = no client / if mcp_client_enabled(): / from tools.mcp_tool_discovery import get_mcp_status / info["mcp_servers"] = get_mcp_sta | **upstream** / mcp |
| 12.09 | `@@ -2543,7 +2559,8 @@ def _make_agent(`<br>`87a293b34937e7ba3b127ea6faa8fae21c5be885b6c00aac190def9a98384f27` | from agent_runtime.conversations.worker_app_functions import create_agent / agent = create_agent(AIAgent, sid, session or {"source": platform_override}, | **upstream** / factory |
| 12.10 | `@@ -2623,7 +2640,7 @@ def _init_session(`<br>`47592413dbdabc5a56769e578f7ea003d4c1015381d72be73eb847c7a36d56dc` | "agent": agent, "session_key": key, "history": history, "history_lock": threading.RLock(), | **upstream** / recovery |
| 12.11 | `@@ -2692,7 +2709,7 @@ def _deferred_session_record(`<br>`da9f5b401ed0ef11876084d3fb30e0995e0353fc0840ad3c9307d5db49de7be8` | "history_lock": threading.RLock(), "history_version": 0, "image_counter": 0, | **upstream** / recovery |
| 12.12 | `@@ -2771,6 +2788,16 @@ def _finalize_superseded_runtimes(stale: list[tuple[str, dict]]) -> None:`<br>`10d896223ab778b9b7f673d6dd2e95a40e6aa2f6c6b3b10f31bf417195e7f266` | if (session := _sessions.get(sid)) is not None: / from agent_runtime.conversations.worker_app_functions import enabled as has_native_app_tools / if has_native_app_tools(session): / session["lazy"] = True  # The | **upstream** / factory |
| 12.13 | `@@ -2924,7 +2951,7 @@ def _find_live_session_by_key(session_key: str, profile_home=_ANY_PROFILE) -> tu`<br>`7e0b863a6187dfb8592af5c1b9e1bd480edb65e8bf2d21bcbb478228883e9e51` | return _session_info(agent, session) | **upstream** / identity |
| 12.14 | `@@ -2933,9 +2960,10 @@ def _fallback_session_info(session: dict) -> dict:`<br>`4aa4ab7de334114f0a05680100e97c4768c8d77a9d9ea928a8f9b55d1f0ed2f6` | model, provider = _live_session_identity(session) / "model": model, "provider": provider, "skills": {}, "tools": {}, "desktop_contract": DESKTOP_BACKEND_CONTRACT, | **upstream** / identity |
| 12.15 | `@@ -3494,17 +3522,36 @@ from . import (  # noqa: E402`<br>`7d3e9b9a2dac1a1c6f5273b996bd221e5ffbda700ef78993e2700d9eca45c012` | try: / from . import methods_connectors as _methods_connectors  # noqa: E402 / from . import methods_connectors_account as _methods_connectors_account  # noqa: E402 / except ImportError:  # fork seam: phone whe | **extract** / registration + optional (mixed registration/import) |
| 12.16 | `@@ -3512,3 +3559,8 @@ for _m in (`<br>`8d3cbe2c052138c42d395fc5acb16cf6de88b4e66ab6c18d2e26ec22a7a355a3` | from . import session_recovery as _session_recovery  # noqa: E402 / _session_recovery.register(sys.modules[__name__]) / from . import session_retirement as _session_retirement  # noqa: E402 / _session_retiremen | **extract** / registration + optional (mixed registration/import) |

### tui_gateway/session_lifecycle.py

Baseline +12/-4; upstream source SHA-256: 22ba865ee54b569be7285439075bdb604dffa915b827844558b1bc1261e9d776; fork source SHA-256: 1af4d52cdf6c2fd4c3968d9d616edd1902025bcb0bf2e0f58d323502ec18c45f.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 13.01 | `@@ -16,9 +16,10 @@ from .method_ctx import bind_module`<br>`ad1dd204541968229e8235b1ed350d71c2d654d965d4f7346eaed3c29ff28b2c` | from tui_gateway.session_execution import control / with retirement.work() as admitted, control(session), session["history_lock"]: / yield admitted and not session.get("_closing") | **upstream** / recovery |
| 13.02 | `@@ -531,6 +532,11 @@ def _teardown_popped_session(session: dict &#124; None, *, end_reason: str = "tui_clo`<br>`24301d95357bc98707eefdc7cdc7f6a359b7b4b7316a858577deb568c70dcd80` | from tui_gateway.recovery_history import discard_history / discard_history(session) / from tui_gateway.event_replay import forget_session / if sid := session.get("_sid"): / forget_session(sid) | **upstream** / recovery |
| 13.03 | `@@ -633,7 +639,8 @@ def _ws_session_is_orphaned(session: dict &#124; None) -> bool:`<br>`afcd5b5a2892335840989c7fd02ec43965afd4052ee4e3aeed485a6816fc2f1c` | def _interrupt_session_turn(sid: str, session: dict, *, request_id: str &#124; None = None, / expected_execution_id: str &#124; None = None) -> bool: | **upstream** / recovery |
| 13.04 | `@@ -643,7 +650,8 @@ def _interrupt_session_turn(sid: str, session: dict, *, request_id: str &#124; None =`<br>`a4447ed4bf73d34cafc958e17f1fe9dd9edd560b1472e754c508c6f52ecc0750` | _get_compute_host_supervisor().interrupt(sid, request_id=request_id, / **({"expected_execution_id": expected_execution_id} if expected_execution_id else {})) | **upstream** / recovery |

### tui_gateway/session_workdir.py

Baseline +12/-2; upstream source SHA-256: 5eef1be8ac6efb178a43a4f61dddc9ef618fdf21ef36034d8a70508b2aa475b8; fork source SHA-256: f7d6f31a2801ff90709e555c9a1912f7219984e76aa4cea2d0d08ac70939752a.

| ID | Hunk header and SHA256 | Fork addition/change | Verdict/policy |
|---|---|---|---|
| 14.01 | `@@ -338,6 +338,10 @@ def _register_session_cwd(session: dict &#124; None) -> None:`<br>`084e4b5577833e2d586b473fc81a1354dde6fc3ff31611f565e84e343a0b7ada` | from agent_runtime.loop_tool_lifecycles import shipped  # fork seam: phone wheel ships no terminal tool / if not shipped("tools.terminal_tool"): / return | **upstream** / optional |
| 14.02 | `@@ -501,7 +505,8 @@ def _persist_branch_seed(session: dict) -> None:`<br>`430374d4244f9d2c85a6cbe90a00b75caf39ad4168653f2d7da475014da686f0` | def _write_submit_user_row(session: dict, text: Any, display_kind: str &#124; None, *, / display_metadata: dict &#124; None = None) -> dict &#124; None: | **upstream** / metadata |
| 14.03 | `@@ -513,6 +518,8 @@ def _write_submit_user_row(session: dict, text: Any, display_kind: str &#124; None) -`<br>`ab9002bff8e094e1ed46861025d828ab445504b47c53ee8161045b2107de0216` | if display_metadata: / staged["display_metadata"] = display_metadata | **upstream** / metadata |
| 14.04 | `@@ -521,6 +528,7 @@ def _write_submit_user_row(session: dict, text: Any, display_kind: str &#124; None) -`<br>`9e25f9957d7587fd4a166eb3a442b7ba5d0bb934d82b41b7b69d980c5f125c49` | display_metadata=display_metadata, | **upstream** / metadata |
| 14.05 | `@@ -537,7 +545,9 @@ def _persist_submit_user_row(session: dict, text: Any, display_kind: str &#124; None)`<br>`df190d9e1403fa1d1cf0147cc49486577c3941f22d627581656ad7f8072c5c17` | execution = session.get("native_execution") / metadata = {"execution_id": execution["id"]} if execution else None / if (staged := _write_submit_user_row(session, text, display_kind, display_metadata=metadata))  | **upstream** / metadata |

## Proven drop 10.01 receipt

Exact unchanged tests/tui_gateway/test_native_replay_recovery.py bytes copied to isolated proof dir; test-only conftest loads only exact upstream event_replay module (stdlib dependencies) under that package name. No fork replay implementation/product monkeypatch. Parent repo conftest excluded to prevent collection widening. Module-level invariant proof, not integrated native recovery qualification.

Command in proof dir: python -m pytest -q -p no:cacheprovider --confcutdir . test_native_replay_recovery.py. Exit 0:1 passed in 0.01s. Killing mutation reintroduced _replay_next_seq.pop(oldest_sid,None) on eviction; same command exit 1:1 failed in 0.07s, test_cache_eviction_does_not_reset_live_session_identity assert latest_seq(active)==before, actual 0 expected 3. Upstream proof file restored after red. Initial invocation wrong cwd exit 4/no tests; corrected once. No full/bundled run.
Fork test SHA-256: ae9ee5e68cd4bea48003653e1ee29938b4054d0a672f9e93a36439a14eda4e76; upstream module blob: c5dac701896ccb7febf7b44fb0e6b6f57340823a. Raw green/red logs preserved as Job 2 session evidence. Keep test after later drop; checkpoint/retirement compatibility requires separate acceptance.

## Proposed implementation clusters — parent batch review first

Exclusive upstream files below; fork-owned destinations change sequentially. No new agents. No automatic next cluster. MOVE and DROP separate commits; positive control required for CHANGE.

| Cluster | Exclusive upstream files | Ordered work/prerequisite | Focused acceptance |
|---|---|---|---|
| Skills (3) | agent/prompt_builder.py; agent/skill_utils.py; tools/skills_tool.py | Resolve upstream tiered-root integration/release prerequisite first, then PR #124191 design/config seeding and differential lookup proof. Move only snapshot/default helpers; remaining visibility/context/catalog ports held with explicit candidates. | tests/agent/test_prompt_builder_downstream.py; tests/agent/test_external_skills_downstream.py; tests/tools/test_skills_tool_downstream.py; PR tests/agent/test_skills_extra_dirs.py after integration. Add snapshot/default/direct catalog gaps; narrow actual touched nodes. |
| Gateway (5) | tui_gateway/event_replay.py; tui_gateway/methods_session.py; tui_gateway/server.py; tui_gateway/session_lifecycle.py; tui_gateway/session_workdir.py | Proven eviction drop requires compatible upstream frozen-ring integration. Keep atomic/retirement APIs; move only extension registration with globals/order/errors preserved. Independently review recovery/identity/thread/client/MCP/UI ports, no second replay/transcript owner. | tests/tui_gateway/test_native_replay_recovery.py; test_native_execution_fence.py; test_native_recovery_snapshot.py; test_native_session_retirement.py; test_local_model_session_identity.py; tests/agent_runtime/test_embedded_phone_session.py; test_native_app_functions.py. Supply missing registration/MCP/UI/compute nodes first; only named touched selection. |
| Remaining (6) | agent/turn_context.py; agent/turn_facade.py; hermes_cli/webhook.py; tools/credential_files.py; tools/environments/local.py; tools/process_registry.py | Windows helper MOVE after exact tests. One-line generic fixes remain upstream candidates; secret/env/process already extracted. Native reuse ROW-PR needs out-of-scope caller review by parent, do not expand without revised design. | tests/agent_runtime/test_mission_chat_turn_context.py; test_host_store_seam.py; test_slot_env_overlay.py; tests/tools/test_credential_files.py; test_process_wait_lane_clamp.py. Add exact native reuse/EOF/webhook/system-PATH gaps. |

Phase A ran no footprint test/tooling/docs gate: no product/fixture change. Only named replay proof above. Parent reviews table before implementation; Claude runs final combined suite, user owns landing.
