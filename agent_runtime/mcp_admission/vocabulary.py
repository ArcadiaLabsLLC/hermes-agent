"""The admission vocabulary: the typed denial codes (plus ``mcp_lane``'s
``MCP_NOT_REGISTERED_ON_LANE``, reused), the lane, the toolset prefix, the
transport words, the parked-wake bound, the read-only tool tables, the
operating skills and the two defaults.

A vocabulary module (sheet ``mcp_admission.md`` §1): exempt from the 100-line floor."""

from __future__ import annotations

import logging
from typing import Mapping

__layer__ = "models"

#: The package's one logger, under the name the single file logged as.
logger = logging.getLogger("agent_runtime.mcp_admission")


# ── typed denial codes ──────────────────────────────────────────────────────
#
# Same vocabulary as the design's §A. ``mcp_not_registered_on_lane`` is reused
# from R0 rather than re-spelled: "admitted, but it did not actually register"
# is exactly what that code already means.


MCP_ADMISSION_DISABLED = "mcp_admission_disabled"
MCP_ADMISSION_LANE_BUSY = "mcp_admission_lane_busy"
MCP_ADMISSION_TIMEOUT = "mcp_admission_timeout"
#: DECLARED (by ``required_mcp_servers`` or the profile's own ``mcp_servers``
#: block), but the persona's profile has no ``mcp_servers`` entry to spawn. The
#: readiness taxonomy already calls this ``mcp_attention``; this is its
#: admission-side spelling.
#:
#: S66 dropped "role-admitted" from this line. There is no role admission — S64
#: made declaration the sole authority — and the phrase named a gate that could
#: not fire.
MCP_SERVER_NOT_CONFIGURED = "mcp_server_not_configured"
#: ``read_only`` can only admit a server whose mutating tools we can name. An
#: unknown server has no reviewer-shaped subset, so read_only admits nothing
#: rather than admitting a surface it cannot subtract.
MCP_READ_ONLY_SUBSET_UNKNOWN = "mcp_read_only_subset_unknown"
#: A finished run's registry scope could not be removed. Never fatal — the turn
#: has already produced its answer by the time teardown runs — but never silent
#: either: leftover scope is exactly the residue R2 exists to retire.
MCP_ADMISSION_TEARDOWN_FAILED = "mcp_admission_teardown_failed"
#: The run spent its per-run admitted-MCP-call budget. Every FURTHER admitted MCP
#: call is refused with this row IN PLACE OF a dispatch; the turn itself is never
#: killed, so the agent can still finish and report with what it already has.
#: Design §3's residual-risk mitigation ("Loop → repeated launches/kills") and
#: the one §7 row R2 shipped without.
MCP_ADMISSION_BUDGET_EXHAUSTED = "mcp_admission_budget_exhausted"
#: This RUNTIME has no MCP client at all — ``tools/mcp_tool`` set
#: ``_MCP_AVAILABLE = False`` because the optional ``mcp`` pip extra is not in
#: the venv, so ``register_mcp_servers`` returns ``[]`` in ~0 ms without
#: consulting a single server.
#:
#: Its own code because the alternative cost weeks. Every such turn used to land
#: on ``mcp_not_registered_on_lane``, whose fix hint says "check the server is
#: running and its command resolves" — the two things that are already fine, and
#: the ONE half of the system that is healthy. The 2026-08-26 root cause records
#: the outcome: a standing "the chat lane admits nothing" gap was planned against
#: for weeks while admission, declaration, resolution and policy were all correct
#: and the runtime simply had no MCP client
#: (``harness-skills/harness-runtime-model/references/operations.md``,
#: "Scope note (2026-08-26)"; ``…/references/proof.md`` lists it as the hazard to
#: check FIRST). This row names the runtime instead of blaming the server.
#:
#: Two facts belong in its hint and are in it. The cure is
#: ``pip install "hermes-agent[mcp]"`` (``pyproject.toml`` — the ``mcp`` extra),
#: and the cure does NOT reach a running process: ``_MCP_AVAILABLE`` is a
#: module-level constant read at import, so the runtime must be restarted.
MCP_SDK_UNAVAILABLE = "mcp_sdk_unavailable"

#: The admission LANE — the runtime surface a persona turn runs on. Distinct
#: from ``mcp_lane``'s entry-point lane (``harness`` / ``chat`` / …), which
#: answers "did this process run MCP discovery". Both are needed: admission is
#: what puts tools on the harness entry point in the first place.
LANE_MISSION_CHAT = "mission_chat"

#: Toolset-name prefix ``tools/mcp_tool.py`` registers every MCP server under.
_MCP_TOOLSET_PREFIX = "mcp-"

#: How an admitted server's tools reached the registry on THIS run.
#:
#: ``warm`` — the transport was already connected with a live session, so
#: registration re-ran over tools this process had already listed. Measured
#: 2026-08-09 against a real 60-tool stdio MCP server: **6–8 ms** for the whole
#: admission, 0.2–0.3 ms for teardown.
#:
#: ``cold`` — no live session, so ``register_mcp_servers`` spawned the server
#: process and completed the MCP handshake before anything could be listed.
#: Measured **3,197 ms** on that same 60-tool stdio server.
#:
#: **That number is ONE server's spawn, and it is not a discriminator**
#: (corrected 2026-08-26; this docstring was one of the two places carrying the
#: bad rule of thumb). An earlier revision read as "~3,200 ms means a real cold
#: spawn", and ``launcher_qa`` — a compiled Dart exe — spawns cold in **~100 ms**,
#: so that rule reads a genuine spawn as a fast failure. It sent a whole
#: investigation down the wrong branch. Spawn cost is a property of the SERVER,
#: not of the path, and no threshold separates the two.
#:
#: **The honest discriminator is the SET, never the clock**: a non-empty
#: ``admitted`` on the outcome, equivalently a non-empty
#: ``mcp_lane.registered_mcp_server_names()`` (the operator-facing spelling is
#: ``mcp_admitted_servers`` on ``profile_timing``). The clock only ever separated
#: ~0 ms from "something happened", and ~0 ms has its own code now
#: (:data:`MCP_SDK_UNAVAILABLE`). No code here reads the elapsed time to decide
#: anything: ``profile_runner`` records ``mcp_admission_cold_servers`` by counting
#: THIS label, and the label is read from the transport map.
#:
#: These labels exist as a RECORDED fact because the difference was being
#: inferred.
#: ``PERF_SEND_ANALYSIS_2026-08-09`` (F2/T2) attributed a flat 2.35–3.4 s per
#: turn to "re-registration of an unchanged server set" and proposed caching the
#: registration. The measurement says registration is the 6 ms half and the spawn
#: is the whole cost — and a spawn is not cacheable, because a tool call needs a
#: live session, not a remembered schema. Its three probe turns each ran in a
#: FRESH CLI process, so all three were cold: turn-1 numbers reported as steady
#: state. The serve lane keeps transports warm across turns by design
#: (``tools/mcp_tool._servers`` outlives the run; only the registry scope is
#: per-run), so a warm serve turn should read ``warm``. Nothing persisted that,
#: so nobody could check which one the live 3.4 s was. Now the turn says.
TRANSPORT_WARM = "warm"
TRANSPORT_COLD = "cold"

#: How long an admission waits for a PARKED server's session to come back after
#: it has asked for one.
#:
#: A cached server with ``session is None`` has no registered tools and cannot
#: be re-registered off a session it does not have. The reconnect that repairs
#: that is asynchronous — it lands on ``tools/mcp_tool``'s background loop — so
#: an admission that nudged and looked once would find nothing and hand the turn
#: zero tools while the cure it had just asked for was already in flight.
#: Measured 2026-08-27 as a 3/0/3/0 alternation across four consecutive
#: mission-chat turns to one session.
#:
#: The BOUND is the point. Waiting is only worth it against the alternative,
#: which is a whole turn with no MCP surface at all; a server that is genuinely
#: gone must not hold the turn open, so this gives up and lets it fall through
#: to the cold path exactly as before. Read at call time so a test can lower it.
_PARKED_WAKE_TIMEOUT_SECONDS = 5.0

#: The launcher-allowlist PROFILE ROW a ``read_only`` admission compiles from.
#: ``read_only`` is "inspect what others captured", which is exactly what that
#: row was written to express — see the parity fixture below.
READ_ONLY_ALLOWLIST_PROFILE = "reviewer"

#: **Positive** per-server tool allowlist for a ``read_only`` admission — the
#: resolved ALLOW set of the ``reviewer`` row of the launcher's own per-profile
#: allowlist, ``EterniaLauncher docs/stages/qa-reboot/launcher_qa_profile_allowlists.yaml``
#: (v1, 2026-05-17, + the Stage 19 / VOICE_QA §5.E / batched-drill amendments —
#: snapshot pinned at launcher ``3e3feff0``, a 26-tool surface).
#:
#: Positive, not negative, deliberately: a tool the launcher's QA server grows
#: LATER is denied to ``read_only`` by default instead of silently inheriting it.
#: That is the same default-deny the launcher YAML chose for its restricted
#: profiles ("so a future tool added under Stage 19+ does not silently fall into
#: the restricted profiles via a missing entry"), and it is the reason this is
#: the R2 shape rather than R1's exclude list.
#:
#: Hermes OWNS this policy (design open question 6): the launcher file is
#: documentation plus a CI parity fixture, never read at admission time, so a
#: missing checkout or a deploy skew can never change what an agent may call.
#: ``tests/agent_runtime/test_mcp_admission_r2.py`` pins it against a vendored,
#: hash-recorded snapshot of that YAML — see the fixture's refresh instructions.
READ_ONLY_INCLUDED_TOOLS: Mapping[str, tuple[str, ...]] = {
    "launcher_qa": (
        "mcp_launcher_qa_get_auth_state",
        "mcp_launcher_qa_get_buttons",
        "mcp_launcher_qa_get_feed_fixture_state",
        "mcp_launcher_qa_get_media_playback_state",
        "mcp_launcher_qa_get_navigation_state",
        "mcp_launcher_qa_get_runtime_state",
        "mcp_launcher_qa_get_voice_state",
        "mcp_launcher_qa_get_widget_state",
        "mcp_launcher_qa_get_window_metrics",
        "mcp_launcher_qa_read_artifact_index",
        "mcp_launcher_qa_read_trace",
        "mcp_launcher_qa_run_redaction_scan",
    ),
}

#: The complement of :data:`READ_ONLY_INCLUDED_TOOLS` over the server's known
#: surface — the ``denied`` rows of the same ``reviewer`` profile. The include
#: list above is what actually gets REGISTERED; this list is the warm-process
#: backstop, threaded into ``blocked_tool_names`` so a resident actor's cached
#: tool definitions cannot resurrect a mutator that the current run's
#: registration already filtered out.
#:
#: R1 carried only this half, and it was three names SHORT of the reviewer row:
#: ``capture_screenshot`` / ``screenshot_window`` / ``wait_for_state`` all drive
#: a live launcher window (restore + foreground + PrintWindow; a polling loop
#: against the fixture mutex) and the launcher denies them to ``reviewer`` for
#: that reason. R2 adopts the row verbatim, which NARROWS ``read_only``.
#:
#: ``run_actions`` is the reason a POSITIVE include is the right shape. It is a
#: capability MULTIPLEXER — one call executing an ordered list of other verbs —
#: so a name-matching allowlist that admits it hands over every batchable verb
#: the profile is otherwise denied. Under an include list it is denied by
#: construction, because it simply is not on the list; under an exclude list it
#: would have been admitted the moment the launcher shipped it, silently, and
#: nobody would have noticed until an agent batched a ``click_button``.
READ_ONLY_EXCLUDED_TOOLS: Mapping[str, tuple[str, ...]] = {
    "launcher_qa": (
        "mcp_launcher_qa_begin_pkce_login",
        "mcp_launcher_qa_capture_screenshot",
        "mcp_launcher_qa_click_button",
        "mcp_launcher_qa_dismiss_hashtag_onboarding",
        "mcp_launcher_qa_kill_launcher",
        "mcp_launcher_qa_launch_or_attach",
        "mcp_launcher_qa_open_app_tab",
        "mcp_launcher_qa_run_actions",
        "mcp_launcher_qa_screenshot_window",
        "mcp_launcher_qa_scroll",
        "mcp_launcher_qa_scroll_to",
        "mcp_launcher_qa_scroll_to_fixture",
        "mcp_launcher_qa_set_tab",
        "mcp_launcher_qa_wait_for_state",
    ),
}

#: The OPERATING MANUAL for each admissible server: the skill(s) that document
#: how to drive that server's surface, and — the part that matters — what to do
#: when it REFUSES. Admitting a tool surface without its manual is what produced
#: the live 2026-07-29 failure: a QA mission-chat turn drove ``launcher_qa``,
#: hit ``helper_low_information_capture`` from ``screenshot_window``, and burned
#: the turn rediscovering nothing — while the remedy (capture a content-bearing
#: sub-tab, or take the documented sparse-acceptance path) sat in a skill the
#: persona was ALREADY granted and that was never put in context.
#:
#: Why the map lives here rather than in the skill's frontmatter
#: -------------------------------------------------------------
#: ``metadata.hermes.load_policy: required_preload`` is the right mechanism for
#: "this persona always needs this skill" (``harness-runtime-model``), and it is
#: reused verbatim downstream — the resolved names join the SAME required-preload
#: set. It is the wrong mechanism for this fact, twice over:
#:
#: * The condition is not "the persona is granted it", it is "this RUN was
#:   admitted the server". A persona that declares ``launcher_qa`` on a lane
#:   where admission is off, or under a role the config does not name, gets no
#:   MCP tools — and must not pay a 45KB manual for tools it does not have.
#: * ``launcher-mcp-operations`` (renamed 2026-08-28 from
#:   ``launcher-stagec-mcp-screenshot``) is not a Harness-owned skill: it is not
#:   under ``docs/agent-runtime-harness/harness-skills`` and ``skill_install``
#:   never writes it, so its frontmatter is a realm-published runtime artifact
#:   that the next realm pull would overwrite. A policy Hermes must hold cannot
#:   live in a file Hermes does not own — the same reasoning that keeps
#:   :data:`READ_ONLY_INCLUDED_TOOLS` here instead of reading the launcher's YAML.
#:
#: Keyed by server, not by role, for the same reason the tool tables are: the
#: manual belongs to the SURFACE. A second role admitted the same server would
#: need the same manual, and a role admitted nothing needs none.
MCP_OPERATING_SKILLS: Mapping[str, tuple[str, ...]] = {
    "launcher_qa": ("launcher-mcp-operations",),
}

_DEFAULT_CONNECT_TIMEOUT_SECONDS = 20.0

#: Per-run budget of ADMITTED MCP tool calls, before an operator config edit.
#:
#: Sized off the real drills rather than a round number: the Stage C 6-row
#: acceptance matrix costs ~60 admitted calls end to end, and the batched
#: ``run_actions`` lane (a 6–9 action drill in ONE call) costs far less. 120 is
#: ~2× the heaviest honest turn we know of, which is the "generous" side of the
#: line — the budget is a loop bound, not a work bound, and a QA turn that trips
#: it has stopped making progress rather than merely being thorough.
_DEFAULT_MAX_TOOL_CALLS_PER_RUN = 120
