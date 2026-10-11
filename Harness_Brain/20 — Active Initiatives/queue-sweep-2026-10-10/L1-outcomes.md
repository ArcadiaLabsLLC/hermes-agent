# L1 outcomes (lane-1010-L1, branch lane/1010-L1)

L1.01 · RETURNED seam: the indexed, lineage-aware content lookup belongs at the SessionDB boundary (`hermes_state.py`, upstream-owned); the fork can only consume a public door, so this is an upstream PR row first.
L1.02 · FIXED 909240453d
L1.03 · RETURNED too big: the 10–11 ms is per-run MCP register+teardown on a reused actor; the design question is a per-actor admission memo (when is an admitted set still valid across runs, who invalidates it) — the verdict already called it structural.
L1.04 · RETURNED operator live proof: re-take warm/cold/idle through the Launcher route on the post-relay head and on a long real history.
L1.05 · RETURNED upstream: the 41 ms is `agent/transports/codex.py::ResponsesApiTransport.build_kwargs` (upstream-owned); the verdict found no fork-side narrow fix, its web-search share is a separate row.
L1.06 · RETURNED too big: needs a peer-tier cancel verb carrying the dispatch id across serve/install boundaries (design: who owns the cancel, how a remote supervisor authenticates it).
L1.07 · FIXED 769892259e
L1.08 · RETURNED too big: one typed params reader with an injected refusal type plus one versioned-JSON-doc reader across six modules exceeds ~150 lines; design question: the refusal-type injection shape each lane's error envelope accepts.
L1.09 · RETURNED operator live proof: delivery landed; live acceptance needs an authenticated QA model/profile (first-response selection, cross-agent, edit/reopen/restart, latency).
L1.10 · RETURNED seam: the reader (`hermes_cli/auth.py`) and the pool (`agent/credential_pool.py`) are upstream-owned and the needs-attention banner is launcher-side; the historical race is still unproved (verdict PENDING).
L1.11 · RETURNED owner decision: the registrar is upstream's blocking register (no cancel door) and the worker must hold the mutex until the global registry settles; question: may the next admission WAIT on the mutex for its budget instead of refusing `mcp_admission_lane_busy` (reverses the ruled refuse-not-wait contract), or does this wait on an upstream cancel?
L1.12 · RETURNED operator live proof: verdict PENDING; isolated cancellation releases the reader, the Launcher hub handoff with a real turn must be reproduced on new code.
L1.13 · RETURNED owner decision: preload-on-demand vs a slimmer launcher-authored SKILL.md (launcher half).
L1.14 · RETURNED operator live proof: stack samples and persistence/title/refresh ablations on a live fast response are the prerequisite; no attribution exists to act on.
L1.15 · RETURNED upstream: assessment only; `title_upgrade_defer.hold_title_upgrade` already covers `codex_responses` and no supported-path gap reproduces offline, so no door is proposed.
L1.16 · RETURNED operator live proof: read `stream_gap_receipt` on ≥5 live Neko turns.
L1.17 · RETURNED operator live proof: re-read turn 1 on the next prewarmed Neko chat.
L1.18 · RETURNED operator live proof: the R4 A/B on a live teammate clarify answer.
L1.19 · RETURNED upstream: `mcp==2.0.0` still hard-codes `experimental=None`; parked to the next mcp pin bump (owner 2026-10-05).
L1.20 · RETURNED too big: a disk-cold import/dispatch profiling program on a QA seed; design question: which of main_import 4.0 s / dispatch 6.0 s move lazy without changing serve readiness semantics.
L1.21 · RETURNED owner decision: the background-long-tool design is owed for approval before any build (turn/await semantics, result re-entry, seams, console).
L1.22 · FIXED 5ab4d97cd1
L1.23 · FIXED 68383414a1
L1.24 · RETURNED seam: measured — fork-owned children (conversation worker, snapshot worker, dispatch child, sign-in child) spawn without `-I` and inherit `PYTHONPYCACHEPREFIX` (served_profile_child_env keeps it); every `sys.executable -I` spawn is in an upstream file (`hermes_cli/local_runtime/devices.py`, `sqlite_runtime.py`, `update_custody.py`, `venv_sync.py`, `update_cmd_commit.py`, `source_completion.py`).
L1.25 · RETURNED too big: routing native conversations through `permission_options_for_chat` needs a design answer (which persona/session record keys an instance conversation's permission) and belongs to the instance-conversation cutover row (TAKEN by L2).
L1.26 · ALREADY-DONE a669de2649 + `tests/agent_runtime/test_thinking_row_order.py` (one stored row per frame in order; pairing moved to stable `reasoning_id`).
L1.27 · RETURNED too big: Eternia Lens is a staged L0–L4 program (plan `eternia-lens-in-hermes.md`), not a lane row.
L1.28 · RETURNED launcher side: `runtime.realm.sync.revert` is on the method lane; owed the launcher binding, then the in-serve timing on a real realm.
L1.29 · FIXED bac9924d86
L1.30 · RETURNED too big: closes when the phone gate prints PASS; the remainder is lanes G1–G6, each its own row.
L1.31 · RETURNED operator live proof: needs the Piper voice pack + openphonemizer-en_us.onnx on a box to profile (owner: profile first).
L1.32 · RETURNED operator live proof: retire only once the owner's installed launcher is at or after 290449df44, else an older launcher's LAN toggle silently stops working.
