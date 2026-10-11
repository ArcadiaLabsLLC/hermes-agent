# L7 outcomes (lane/1010-L7)

L7.01 · RETURNED upstream: reproduced (routing_authz red after residue_parity in one process, both green alone); tests/conftest.py's hermetic step 3b pins hermes_state.DEFAULT_DB_PATH only when hermes_state is already imported, so `_classify_completion_target` reads the pin instead of team_b's store (`('terminal','terminal')`); both files are upstream and need the unpin test_housekeeping_profile_scope.py's fixture does, or the pin made order-independent — upstream issue draft, never posted
L7.02 · RETURNED workstation hazard: Norton Web/Mail Shield intercepts loopback TLS on this box; attributing the 68 nodes needs a run with interception excluded for the connection (operator), pin stays enforced
L7.03 · ALREADY-DONE tests/tooling/test_function_legibility_floor.py 4 passed on 751532d1bf (scripts/run_tests.sh)
L7.04 · RETURNED owner decision: may bundled-plugin discovery (`discover_plugins`, ~48% of test_persona_assignments CPU) be session-cached across tests instead of reset by `_hermetic_environment` per test?
L7.05 · FIXED bc80f72d5d
L7.06 · RETURNED upstream: the door is an additive public accessor in upstream tests/conftest.py (`_REAL_HERMES_ROOT_CANDIDATES` is also MUTATED by the fork's second site); needs a held PR row in the footprint ledger, not a lane edit
L7.07 · FIXED 53ccebb5e1
L7.08 · ALREADY-DONE tests/hermes_cli/test_chat_tool_progress_stream.py 10 passed on 751532d1bf (last touched 78413597a0)
L7.09 · FIXED f596b636fe (gate already green via c3894ae54d/bd6b08a7b3; the two remaining line cites pointed at the wrong lines and are now symbol cites)
L7.10 · ALREADY-DONE d04f2766ca (DefaultModelRefused inherits ProviderRefused's constructor); duplicate gate 5 passed
L7.11 · ALREADY-DONE d04f2766ca (W0-G3 renames); duplicate gate 5 passed on 751532d1bf
L7.12 · RETURNED upstream: pm/downloader.py builds `_OPENER` (HTTPSHandler, reads SSLKEYLOGFILE) at module scope; draft PR = lazy opener on first request, never posted; host trigger is an inherited SSLKEYLOGFILE
L7.13 · RETURNED owner decision (standing trigger): re-checked at v0.21.6 — upstream tui_gateway/host_supervisor.py still probes `os.kill(pid, 0)`, so the carry stays; re-check at the next release merge
L7.14 · RETURNED upstream: part 1 is draft #131905; part 2 needs upstream's Windows tests run in a clean upstream worktree with the live-guard refusal applied (the measurement), then the PR — an upstream lane, not this one
L7.15 · RETURNED owner decision: the row is flagged to the owner (move tui_gateway/compute_model_selection.py when the chat-first seam lands, or say no and the footprint lane does it)
L7.16 · RETURNED upstream: the stray frame's emitter is upstream test_prompt_submit_truncates_by_message_id's unjoined `_run_after_agent_ready` thread (verdict 09-24) and both files are upstream; not reproduced alone today; the five-file set that reds was never recorded
L7.17 · RETURNED operator live proof: Issues enabled 2026-09-29; the row closes when the next red main push upserts the "CI red on main" issue
L7.18 · RETURNED upstream: hold per 2026-10-02 verdict (feature_request issue first, then the credential_io door PR)
L7.19 · RETURNED upstream: reproduced on 751532d1bf (7 failed with housekeeping first; test_anon_sign_in_flow.py alone now 23 passed); the writer is upstream production code — the MCP reconcile chore (`run_profile_reconcile._reconcile_current` -> `mcp_tool_config._load_mcp_config` -> `load_hermes_dotenv(override=True)`) writes the launch profile's NOUS_INFERENCE_BASE_URL into os.environ under a multiplexed gateway; issue draft, never posted
L7.20 · RETURNED too big: routing every e2e/live-serve fixture's home through HERMES_TEST_TMP_ROOT plus a session-finish sweep spans the e2e tree; design question: one fork fixture that owns temp homes, or a runner-level TEMP/TMP override
L7.21 · FIXED 1fcb13d519
L7.22 · FIXED 48ccf324ad
L7.23 · ALREADY-DONE 3002eaa067 (merge body: both gateway-contract files arrived as upstream's copy via the regen driver; gen_gateway_contracts.py --check green)
L7.24 · FIXED 65ba364f0a
L7.25 · FIXED 995d2427a3
L7.26 · ALREADY-DONE 6e574cc3d2 (fixture 176 -> 184) and bc7ecdddd0 (re-based at v0.21.6); test_upstream_footprint 7 passed
L7.27 · FIXED 53f4504bcd (test_coverage_claims_resolve.py already carried timeout(180))
L7.28 · RETURNED too big: not reproduced (3/3 green today); a calibrated 300 ms GIL hold made it slower, and a 70 ms hold still passed, so hold length is not the lever — the lag mechanism needs tracing in a failing run before a fix
L7.29 · ALREADY-DONE c8be21a167 (upstream's own v0.21.6 Windows red, id-marked; the node xfails, upstream file)
L7.30 · ALREADY-DONE ca705dbf7e (upstream #128010 reads the as-const list); 19 passed
L7.31 · RETURNED workstation hazard: shared venv has nemo-relay 0.8.4 vs pyproject `>=0.9,<0.10`; bumping <test venv> while eight lanes run on it is the operator's call (`uv pip install "nemo-relay>=0.9,<0.10"` when idle)
L7.32 · RETURNED upstream: the 5 s is upstream pm/client.py's `process.wait(timeout=5)` for the worker's EXIT after its result arrived (hermes_cli/venv_sync.py prints it, also upstream); draft: a received result with a slow exit should not fail the completion
L7.33 · FIXED 1397507fc0
L7.34 · FIXED 2e9f580052
L7.35 · RETURNED too big: the supersession pass over the 21 kept hunks is its own owner-offered lane (needs upstream v0.21.6 diffs per hunk and the [up-fp] before/after)
