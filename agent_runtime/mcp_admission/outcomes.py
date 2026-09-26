"""The typed outcomes and the one line that renders them: the denial, the
admission, the admission and teardown outcomes, the per-run call budget, and
``render_mcp_admission_line``."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Mapping

from .vocabulary import MCP_DENIAL_CODES, machine_root_issue_codes, MCP_ADMISSION_BUDGET_EXHAUSTED, _DEFAULT_CONNECT_TIMEOUT_SECONDS, _DEFAULT_MAX_TOOL_CALLS_PER_RUN

__layer__ = "models"


@dataclass(frozen=True, slots=True)
class McpAdmissionDenial:
    """One typed reason a declared MCP server is not available for this run.

    ``row()`` is deliberately the same shape as ``machine_roots.PathTokenIssue.row()``
    and the R0 ``mcp_not_registered_on_lane`` row, so operator surfaces that
    already render typed issue rows need no new case.
    """

    server: str
    code: str
    summary: str
    fix_hint: str = ""

    def __post_init__(self) -> None:
        # A denial is a typed reason from a closed vocabulary (rule 14): a code
        # outside it is refused here, at construction, never shipped as a free
        # string an operator surface would have to guess at.
        if self.code not in MCP_DENIAL_CODES and self.code not in machine_root_issue_codes():
            raise ValueError(
                f"McpAdmissionDenial code {self.code!r} is not in MCP_DENIAL_CODES "
                "or the machine_roots issue taxonomy"
            )

    def row(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "server": self.server,
            "summary": self.summary,
            "fix_hint": self.fix_hint,
        }


@dataclass(frozen=True, slots=True)
class McpAdmission:
    """The resolved, side-effect-free answer to "what may this run register?"

    Resolution NEVER spawns, connects or registers anything — it is pure policy
    over config + the persona's declaration, so an operator can inspect it
    (``hermes harness persona tool-diff <id> --explain-mcp``) before the flag is
    ever flipped, and so the whole transition table is unit-testable.
    """

    lane: str
    role: str
    permission_mode: str
    enabled: bool
    requested: tuple[str, ...] = ()
    server_names: tuple[str, ...] = ()
    denied: tuple[McpAdmissionDenial, ...] = ()
    server_configs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: Prefixed registry names removed from the model's tool list for this run
    #: (the resident-actor backstop behind the ``read_only`` include list; see
    #: the module docstring's R2 section).
    blocked_tool_names: tuple[str, ...] = ()
    connect_timeout_seconds: float = _DEFAULT_CONNECT_TIMEOUT_SECONDS
    #: How many ADMITTED MCP tool calls this run may dispatch in total, across
    #: every admitted server. Resolved here (policy) and enforced at execution by
    #: :class:`McpCallBudget`, so an operator can read the bound out of
    #: ``--explain-mcp`` before the flag is ever flipped.
    max_tool_calls_per_run: int = _DEFAULT_MAX_TOOL_CALLS_PER_RUN

    @property
    def is_empty(self) -> bool:
        return not self.server_names

    def denial_rows(self) -> list[dict[str, Any]]:
        return [denial.row() for denial in self.denied]

    def explain(self) -> dict[str, Any]:
        """Stable, machine-readable operator view. No side effects."""

        return {
            "lane": self.lane,
            "role": self.role,
            "permission_mode": self.permission_mode,
            "enabled": self.enabled,
            "requested": list(self.requested),
            "admitted": list(self.server_names),
            "denied": self.denial_rows(),
            # The COMPILED positive allowlist per admitted server — what will
            # actually be registered. Absent/empty means "everything this server
            # advertises" (the launcher's full-capability glob rows). An operator
            # checking a read_only shape before flipping the flag needs to see
            # the include, not infer it from the block list.
            "tool_include": {
                name: sorted(str(tool) for tool in (config.get("tools") or {}).get("include") or [])
                for name, config in self.server_configs.items()
            },
            "blocked_tool_names": list(self.blocked_tool_names),
            "connect_timeout_seconds": self.connect_timeout_seconds,
            # The call bound this run would enforce. Reported even when nothing
            # is admitted: "how many MCP calls could this persona make" is a
            # question an operator asks BEFORE deciding to admit anything.
            "max_tool_calls_per_run": self.max_tool_calls_per_run,
        }


@dataclass(frozen=True, slots=True)
class McpAdmissionOutcome:
    """What actually happened when an admission was executed."""

    admitted: tuple[str, ...] = ()
    denied: tuple[McpAdmissionDenial, ...] = ()
    duration_ms: int = 0
    attempted: bool = False
    #: The subset of ``denied`` that EXECUTION minted — busy / timeout /
    #: admitted-but-did-not-register. Kept separate from the policy denials
    #: ``denied`` also carries, because only these were unknowable when the
    #: turn's runtime-context envelope was sealed, and therefore only these need
    #: the runner's in-band backstop. Reporting a policy denial twice would tell
    #: the agent the same thing in two voices.
    execution_denied: tuple[McpAdmissionDenial, ...] = ()
    #: The live per-run call meter installed over this run's admitted tools, or
    #: ``None`` when nothing registered. Carried on the outcome (rather than kept
    #: module-global) because the budget IS per-run: a new admission mints a new
    #: meter, and the old one dies with the run's registry scope.
    call_budget: "McpCallBudget | None" = None
    #: ``{server: "warm" | "cold"}`` as observed BEFORE this run registered
    #: anything — the one attribution that turns ``mcp_admission_ms`` from a
    #: number into an explanation. Empty when a caller supplied its own
    #: ``register`` (tests, previews): classification reads the live transport
    #: map, and a custom registrar means there is no live transport to read.
    transport_paths: Mapping[str, str] = field(default_factory=dict)

    def denial_rows(self) -> list[dict[str, Any]]:
        return [denial.row() for denial in self.denied]

    @property
    def degraded(self) -> bool:
        """Did EXECUTION fail to deliver something the policy already admitted?"""

        return bool(self.attempted and self.execution_denied)


@dataclass(frozen=True, slots=True)
class McpTeardownOutcome:
    """What the end-of-run registry-scope removal actually removed.

    Advisory, never fatal: by the time teardown runs the turn has already
    produced its answer, so a fault here is reported as a typed row and the run
    still completes. ``failures`` being non-empty is the signal that a scope
    outlived its run and the next run's toolset scope
    (:func:`scope_toolsets_to_admission`) is carrying isolation alone.
    """

    servers: tuple[str, ...] = ()
    removed_tool_names: tuple[str, ...] = ()
    failures: tuple[McpAdmissionDenial, ...] = ()
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return not self.failures

    def failure_rows(self) -> list[dict[str, Any]]:
        return [failure.row() for failure in self.failures]


class McpCallBudget:
    """The per-run bound on how many ADMITTED MCP calls a turn may dispatch.

    Why a call budget exists at all
    -------------------------------
    Single-flight bounds how many admissions may be in flight. The wall budget
    and the AS0 liveness watchdog bound the turn's CLOCK. None of them bounds how
    many times an admitted agent may call ``kill_launcher`` inside one turn — a
    model under prompt-injection or simple mechanical looping can spend a whole
    wall budget re-driving a GUI. This is the counter that closes that gap
    (design §3, residual risk 1; §7's owed ``mcp_admission_budget_exhausted``).

    What counts
    -----------
    ONE dispatch of ONE admitted MCP tool = ONE call. That includes the launcher's
    batched ``run_actions`` multiplexer, which executes an ordered list of verbs
    in a single call: §7 says nothing else, and counting the batch as one call is
    what keeps the budget aligned with the seam it is enforced at (a tool
    dispatch), rather than with a payload shape hermes does not parse. It is also
    the direction that keeps the batched lane cheap — which is the lane the QA
    drills are supposed to prefer.

    Nothing else touches the counter: a non-admitted tool (every built-in, every
    other toolset) never passes through the meter, and a call REFUSED after
    exhaustion is recorded as ``refused`` rather than spending budget it does not
    have.

    Scope
    -----
    Per RUN, and per run TOTAL across all admitted servers — deliberately the
    tighter of the two readings the design contains (§3 says "max tool calls per
    admitted server per run"; §7 says "the per-run call budget"). With today's
    single admissible server they are identical; with two admitted servers a
    per-server reading would silently authorise 2× the calls, and the conservative
    direction is the one that cannot surprise an operator upward. Per-server
    counts are still recorded, for the accounting an operator reads afterwards.

    A new meter is minted per admission, so the budget resets per run by
    construction — there is no reset path to forget to call.

    Thread-safe: an agent may dispatch tool calls from more than one thread, and
    a bound that can be raced is not a bound.
    """

    __slots__ = ("limit", "_lock", "_spent", "_refused", "_per_server")

    def __init__(self, limit: int):
        self.limit = max(1, int(limit))
        self._lock = threading.Lock()
        self._spent = 0
        self._refused = 0
        self._per_server: dict[str, int] = {}

    @property
    def spent(self) -> int:
        with self._lock:
            return self._spent

    @property
    def refused(self) -> int:
        with self._lock:
            return self._refused

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.limit - self._spent)

    @property
    def exhausted(self) -> bool:
        with self._lock:
            return self._spent >= self.limit

    def consume(self, server: str, tool: str) -> McpAdmissionDenial | None:
        """Charge one admitted MCP call. ``None`` ⇒ dispatch; a denial ⇒ refuse.

        The check and the increment are one atomic step, so N concurrent calls at
        the boundary cannot all read "one left" and all dispatch.
        """

        with self._lock:
            if self._spent >= self.limit:
                self._refused += 1
                return self._denial(server, tool)
            self._spent += 1
            self._per_server[server] = self._per_server.get(server, 0) + 1
        return None

    def _denial(self, server: str, tool: str) -> McpAdmissionDenial:
        return McpAdmissionDenial(
            server=server,
            code=MCP_ADMISSION_BUDGET_EXHAUSTED,
            summary=(
                f"This run has spent its per-run MCP call budget ({self.limit} admitted "
                f"call(s)), so '{tool}' was NOT executed. No further MCP calls will run "
                "for this turn."
            ),
            fix_hint=(
                "This is a loop bound, not a permission problem: do not retry, do not "
                "hunt for a permission mode, and do not substitute a shell/PowerShell "
                "workaround or a second lane. Finish the turn with what you already "
                "have — report what you captured and what is missing. An operator can "
                "raise agent_runtime.mcp_admission.max_tool_calls_per_run in the ROOT "
                "config.yaml if a drill legitimately needs more."
            ),
        )

    def snapshot(self) -> dict[str, Any]:
        """Accounting for the operator surfaces. Never used to make a decision."""

        with self._lock:
            return {
                "limit": self.limit,
                "spent": self._spent,
                "remaining": max(0, self.limit - self._spent),
                "refused": self._refused,
                "exhausted": self._spent >= self.limit,
                "per_server": dict(self._per_server),
            }


#: Bullet prefix, so the line sits in the same list the wall-budget line renders
#: into on the runtime-context envelope's volatile tail.
_ADMISSION_LINE_PREFIX = "- MCP tools:"


def render_mcp_admission_line(
    admission: "McpAdmission | None",
    *,
    outcome: "McpAdmissionOutcome | None" = None,
) -> str:
    """One compact, agent-visible line naming what this turn did NOT get.

    Design §D3. The third visibility surface, and the one that retires W3: a QA
    agent that sees no ``mcp__launcher_qa__*`` tools and no explanation invents
    alternatives (which is how ``pwsh -File`` calls end up in agent output and
    why the launcher repo needs a grep gate for them). Telling it the truth in
    band is cheaper than fencing every workaround it can invent.

    Returns ``""`` when there is genuinely nothing to say: no admission at all,
    or an admission that declared nothing and denied nothing. A persona with no
    MCP server still pays nothing.

    **Every admission that HAPPENED names its servers** (operator ruling,
    2026-07-27). One sentence, two shapes:

    * a PARTIAL admission appends the admitted names after the denial wording;
    * a fully-CLEAN admission renders that sentence on its own.

    The denial half alone is actively misleading on a mixed turn: an agent told
    only "launcher_qa is dark" reads "MCP is dark" and improvises around the
    server it actually has — the same W3 improvisation this line exists to stop,
    arrived at from the other direction. The clean case used to stay silent on
    the theory that an agent which HAS the tools needs no telling; that theory
    assumes the agent reads its tool list rather than its turn context, and when
    it does not, silence is indistinguishable from absence — W3 again, from a
    third direction. Naming what it has costs one sentence and removes the
    inference.

    The denial wording itself is untouched in both shapes, so the flag-on /
    flag-off "one voice" contract on it is byte-for-byte the same
    (``test_mcp_lane_agent_context_line``).

    ``outcome`` contributes only its ``execution_denied`` rows (busy / timeout /
    admitted-but-did-not-register). The policy denials it also carries are
    already on the turn's envelope, and saying the same thing twice in two
    voices is how an agent learns to discount both. Pass ``admission=None`` with
    an ``outcome`` to render the execution half alone — that is what the runner's
    in-band backstop does.

    Pure and volatile: rendered per turn onto the runtime-context envelope's
    volatile tail (exactly like ``turn_budget.render_turn_budget_line``) and
    never folded into the hashed HUD body, so a cached ``unchanged`` delivery can
    never show the agent a stale capability claim.
    """

    denials = list(admission.denied) if admission is not None else []
    if outcome is not None:
        seen = {(denial.server, denial.code) for denial in denials}
        denials.extend(
            denial
            for denial in outcome.execution_denied
            if (denial.server, denial.code) not in seen
        )
    if not denials:
        # Nothing was refused. If something was ADMITTED, say so — the positive
        # half is the whole line on a clean turn.
        clean = _admitted_clause(admission, {})
        return f"{_ADMISSION_LINE_PREFIX}{clean}" if clean else ""

    # One entry per server, first (most specific) code wins — resolution denials
    # are ordered narrowest-first and execution rows are appended after them.
    ordered: dict[str, str] = {}
    for denial in denials:
        ordered.setdefault(str(denial.server), str(denial.code))
    detail = ", ".join(f"{server} ({code})" for server, code in ordered.items())
    return (
        f"{_ADMISSION_LINE_PREFIX} {detail} — declared for this persona but NOT available "
        "on this turn, so no mcp__<server>__* tools for it are in your tool list. This is a "
        "capability fact, not a permission problem: do not retry, do not hunt for a "
        "permission mode, and do not substitute a shell/PowerShell workaround or a second "
        "lane. There is no harness-side fallback contract to take instead — that lane no "
        "longer exists, so this route is closed for the turn. Say plainly in your reply "
        "that the tools were unavailable and what you could not verify without them, then "
        "finish the turn. Only an operator can lift this, by fixing the condition the code "
        "above names in the root or persona-profile config.yaml."
        + _admitted_clause(admission, ordered)
    )


def _admitted_clause(
    admission: "McpAdmission | None", denied_servers: "Mapping[str, str]"
) -> str:
    """The positive half of an admission — ``""`` when nothing was admitted.

    Rendered on BOTH shapes: appended after the denial wording on a partial
    admission, and standing alone as the whole line on a clean one. Same bytes
    either way, so there is one sentence to read and one place to change it.

    Admitted-then-degraded servers are excluded by construction: anything that
    reached ``execution_denied`` is already in ``denied_servers``, so a server
    can never be reported as both available and unavailable on one line.
    """

    names = [
        str(server)
        for server in getattr(admission, "server_names", ()) or ()
        if str(server) and str(server) not in denied_servers
    ]
    if not names:
        return ""
    listed = ", ".join(dict.fromkeys(names))
    return (
        f" Admitted on this turn: {listed}; those servers' mcp__<server>__* tools ARE "
        "in your tool list, so call them directly."
    )
