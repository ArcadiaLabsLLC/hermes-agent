# L8 outcomes (lane 1010-L8, branch lane/1010-L8, 2026-10-10)

L8.01 · RETURNED design: reproduced today (FLAKY attempt 1: warm turns anchor->request_sent 716/1129 ms > the ABSOLUTE 600 ms bound, green on retry, 2 workers + 7 other lanes); a load-relative budget needs a load reference the suite does not have (no calibration helper exists) — question: calibrate per run, or assert span budgets only on a quiet box (solo does not help: other lanes' load is the cause)
L8.02 · RETURNED upstream: upstream red, carried as `_up_red` in upstream_reds_v0216.py; cause is upstream `tools/terminal_tool._is_unusable_container_cwd` using host `os.path.isabs`, which on CPython 3.13+/Windows calls `/workspace` non-absolute (all 7 paths return True); draft fix: judge container paths with `posixpath.isabs`
L8.03 · FIXED 38bd6d8573
L8.04 · RETURNED too big: counting fresh SessionDBs needs an instrumented run over all 606 tests/agent_runtime files (outside a lane's test budget); widening is then per file, excluding files whose subject is the schema path
L8.05 · ALREADY-DONE bcda4925e0 (Stage 3: bundles cut by duration, slow files solo and submitted first; landed before the 4A lane's 3a22204883 body); no further 4A saving to take
L8.06 · RETURNED workstation hazard: the reproduction (bare pytest across directories) starts a real `gateway run` when the fence is unarmed; not run here
L8.07 · ALREADY-DONE d677799521 (4/4 green today)
L8.08 · ALREADY-DONE 6a9d02b08d (seam moved to chat_verbs.turn_resolve; 5/5 green today)
L8.09 · ALREADY-DONE 6a9d02b08d + d677799521 (peers join now+30d, tool count, provider; 5/23/4 green today)
L8.10 · RETURNED too big (part fixed): the realm-history ordering half is FIXED d1e35aec6a; the download-pause, local_models, delivery_directive, realm_revert and Git fixture residuals pass isolated and need the validated-suite bundle runs to bisect (outside the lane budget)
L8.11 · RETURNED too big: re-qualifying every `_up_red` node means running ~200 upstream test files on the venv — the weekly merge lane's run, not a lane's
L8.12 · RETURNED upstream: PR #128853 (`*.lock` excluded from backups) still open; v0.21.6 `hermes_cli/backup.py` still excludes only `.backup.lock`; row retires at the merge that brings it in
L8.13 · RETURNED too big: classification needs the validated suite (~1 h) on an isolated host; latest evidence (2026-10-10, 97 residual nodes) already matches untouched main
L8.14 · RETURNED owner decision: remaining seams are owner-ruled carries (13 credential seams) or wait on the optional-SDK row (3 builder branches) and the named files' owners; nothing movable left in this lane's scope
L8.15 · RETURNED owner decision: KEEP ruling stands; `guard_fork_history` still live (update_cmd.py), PR #125265 open; the retire-or-keep re-read belongs to the v0.21.6 supersession pass row
L8.16 · ALREADY-DONE: tests/hermes_cli/test_gateway_foreign_xdg_runtime.py now skips all 10 cases on win32 (run alone 2026-10-10: 10 skipped), so the `os.getuid` branch cannot red here
L8.17 · RETURNED owner decision: owner 2026-09-29 "leave, low priority"; parked until a design sitting picks the handler fence
L8.18 · RETURNED upstream: carried as `_up_red` in upstream_reds.py (1 xfail today); `[WinError 2]` omits the binary name — an upstream message fix in the MCP connect-error text
L8.19 · RETURNED too big: still leaking after the 10-03 fence (newest user-Path entries 2026-10-07 20:57–22:44: rb7/ro9/rs7/p-l-longrun launcher sandboxes); a second writer the Python audit-hook fence cannot see: scripts/install.ps1 `[Environment]::SetEnvironmentVariable("Path", …, "User")` driven by tests/scripts/test_install_ps1_desktop_stage.py (leaked `…test_desktop_stage_uses_pm_syn-25\hermes-home\bin`); reproducing writes the operator's PATH (workstation hazard)
L8.20 · RETURNED too big: locating the writer needs a whole-tree gate run (not a lane's); candidate cause: a `git status`/`git diff` against the checkout killed mid-refresh (optional index lock); candidate fix: `GIT_OPTIONAL_LOCKS=0` in the runners' child env — unproven
L8.21 · FIXED d1e35aec6a
L8.22 · ALREADY-DONE bc7ecdddd0 (v0.21.6 merge: tirith_security.py and tirith_config.py gone, no tirith in code or bundled-phone.yaml, ledger line records the four rows retired)
L8.23 · FIXED 5ff812a027
L8.24 · RETURNED owner decision: the `nekwo` account's CreatePullRequest/ready-for-review FORBIDDEN is maintainer-side; nothing a lane can do
L8.25 · RETURNED too big: resolving emitters through the import graph is a rewrite of the scan (resolve each handler's called names to their defining module, fixpoint on `emit_json`), ~150+ lines with its own killing mutation
L8.26 · ALREADY-DONE 6a9d02b08d: sweep 2026-10-10 of the 520 fork-owned test files holding 2026+ date literals found two expiry-shaped literals, both inert (bundle_vuln_scan judges against a fixed TODAY; turn_context's expires_at is a digest-churn field); no other dated literal is compared with now
L8.27 · RETURNED owner decision: process rule, not code — question: name the pinning tests in the producer's docstring (convention) or build a gate (which needs a producer→pin map design)
L8.28 · RETURNED upstream: every named node is now carried as `_up_red` in upstream_reds_v0216.py / posix_marks.py; the fixes are upstream portability (remote-path expectations, Windows casing, `fcntl`)
L8.29 · RETURNED workstation hazard: tests/tui_gateway/test_serve_exit_flush.py kills its pytest process (signal delivery on Windows can reach the console group other lanes share); not run; needs a bounded-child design through the fork test seam
L8.30 · RETURNED upstream: draft — `hermes_cli/tools_config._enabled_plugin_toolsets` adds default-on plugin toolsets even when `platform_toolsets.<p>` is an explicit `[]`; an explicit empty list should mean none (reopens #82010); strict xfail stays in fork_marks
L8.31 · FIXED a0cbe49e98
L8.32 · ALREADY-DONE 8e805c51f4 (roster fixture declares its seeds under the omission guard; 4/4 green today)
L8.33 · FIXED 068eb5a614
L8.34 · FIXED 4b30cedda3
L8.35 · RETURNED design: green today (5/5 alone), but the 500 ms floor exceeds the 300 ms server hold, so passing depends on the hog stretching the client side; a longer hold flips `wait_on` to `server` (server_wait grows with it) — question: how to hold the window open without growing server_wait (e.g. a client-side hold before the first parse)
