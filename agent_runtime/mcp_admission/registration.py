"""The registry scope's two ends (invariants 4-6): ``admit_mcp_servers`` under
the single-flight mutex with its per-run call budget, and
``teardown_mcp_admission``."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from .vocabulary import MCP_NOT_REGISTERED_ON_LANE
from ..serde import positive_float

from .outcomes import McpAdmission, McpAdmissionDenial, McpAdmissionOutcome, McpCallBudget, McpTeardownOutcome
from .transport import _default_registrar, classify_admission_transport, mcp_sdk_available
from .vocabulary import MCP_ADMISSION_LANE_BUSY, MCP_ADMISSION_TEARDOWN_FAILED, MCP_ADMISSION_TIMEOUT, MCP_SDK_UNAVAILABLE, _MCP_TOOLSET_PREFIX, logger

__layer__ = "lanes"


#: Process-wide admission mutex. Held for the FULL duration of a registration
#: attempt — including past a caller's timeout — because the worker thread, not
#: the caller, releases it. A second admission that arrives while one is in
#: flight is refused, never interleaved.
_ADMISSION_LOCK = threading.Lock()


def admit_mcp_servers(
    admission: McpAdmission | None,
    *,
    register: Callable[[Mapping[str, Mapping[str, Any]]], Any] | None = None,
    timeout_seconds: float | None = None,
    on_budget_exhausted: Callable[[McpAdmissionDenial, dict[str, Any]], None] | None = None,
) -> McpAdmissionOutcome:
    """Register the admitted servers' tools for this run. Bounded, single-flight.

    Returns an outcome rather than raising: a capability probe must never be able
    to fail a turn. Every degradation is typed —
    ``mcp_admission_lane_busy`` (another admission in flight),
    ``mcp_admission_timeout`` (budget exhausted; the registrar keeps running in
    the background and may land for a LATER turn, which is why the timeout row
    says "not available for this turn" rather than "failed"), and
    ``mcp_not_registered_on_lane`` (the registrar returned but the server is not
    in the registry) — so the turn can state the truth and finish without the
    server. There is no fallback lane behind these codes: the harness-side
    ``qa.request_screenshot`` decision contract they used to point at was removed
    with the mission lane, so a denial is terminal for this route. The agent-facing
    wording says exactly that and names the operator as the only one who can lift
    it — being pointed at a lane that does not exist is the improvisation the
    sentence was written to prevent.

    Registration is also where the run's CALL budget is armed: every tool this
    admission puts in the registry is metered by a fresh :class:`McpCallBudget`
    before the caller is allowed to construct the agent, so a run can never see
    an admitted tool that is not counted. ``on_budget_exhausted`` is an optional,
    never-raising notification for the operator surfaces (the runner turns it
    into a ``run.progress`` row); it is called on the FIRST refusal only, from
    whichever thread dispatched the tool.
    """

    if admission is None or admission.is_empty:
        return McpAdmissionOutcome(denied=tuple(admission.denied) if admission else ())
    return Admission(
        admission,
        register=register,
        timeout_seconds=timeout_seconds,
        on_budget_exhausted=on_budget_exhausted,
    ).run()


class Admission:
    """One :func:`admit_mcp_servers` call, as its phases.

    ``run`` = :meth:`acquire` (the single-flight mutex; a held one is a typed
    ``lane_busy``) → :meth:`classify` (warm / cold, after the mutex and before
    the registrar) → the meter (one :class:`McpCallBudget` per admission) →
    :meth:`register_bounded` (the worker, waited on for the bounded budget) →
    :meth:`timed_out` or :meth:`outcome`. The WORKER releases the mutex, never the
    caller (:meth:`_work`'s ``finally``): on a timeout the caller returns while the
    registration is still connecting.
    """

    def __init__(
        self,
        admission: McpAdmission,
        *,
        register: Callable[[Mapping[str, Mapping[str, Any]]], Any] | None,
        timeout_seconds: float | None,
        on_budget_exhausted: Callable[[McpAdmissionDenial, dict[str, Any]], None] | None,
    ) -> None:
        self.admission = admission
        self.register = register
        self.on_budget_exhausted = on_budget_exhausted
        self.budget = positive_float(timeout_seconds) or admission.connect_timeout_seconds
        self.servers = dict(admission.server_configs)
        self.started = time.perf_counter()
        self.done = threading.Event()
        self.box: dict[str, Any] = {}
        self.transport_paths: dict[str, str] = {}
        # One meter per admission ⇒ the budget resets per run by construction, with
        # no reset path to forget to call.
        self.call_budget = McpCallBudget(admission.max_tool_calls_per_run)

    def run(self) -> McpAdmissionOutcome:
        busy = self.acquire()
        if busy is not None:
            return busy
        self.classify()
        finished = self.register_bounded()
        if finished is None:
            return McpAdmissionOutcome(attempted=True, denied=tuple(self.admission.denied))
        duration_ms = self.elapsed_ms()
        return self.outcome(duration_ms) if finished else self.timed_out(duration_ms)

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    def acquire(self) -> McpAdmissionOutcome | None:
        if _ADMISSION_LOCK.acquire(blocking=False):
            return None
        busy = tuple(
            McpAdmissionDenial(
                server=name,
                code=MCP_ADMISSION_LANE_BUSY,
                summary=(
                    f"Another MCP admission is in flight in this process, so '{name}' "
                    "was not registered for this turn."
                ),
                fix_hint=(
                    "MCP registration is process-global; admissions are serialized on "
                    "purpose. There is no harness-side contract to take instead, so the "
                    "only routes are: retry the turn, or finish this one without the "
                    "server and say what went unverified."
                ),
            )
            for name in self.admission.server_names
        )
        return McpAdmissionOutcome(
            attempted=True,
            duration_ms=self.elapsed_ms(),
            denied=tuple(self.admission.denied) + busy,
            execution_denied=busy,
        )

    def classify(self) -> None:
        # Classified HERE — after the mutex, before the registrar — because both
        # facts have to be true at once: nothing else can be registering (so the
        # reading is not racing another admission's spawn), and this run has not yet
        # registered anything (so a cold server still reads cold). Only on the
        # production path: a caller-supplied ``register`` means the live transport
        # map is not what will be consulted, and classifying against it would be a
        # confident label for a path that was never taken.
        if self.register is None:
            self.transport_paths = classify_admission_transport(self.admission.server_names)

    def _work(self) -> None:
        try:
            registrar = self.register or _default_registrar
            self.box["tools"] = registrar(self.servers)
            # Meter INSIDE the worker, still holding the admission mutex, so a
            # registration that outran the caller's timeout and lands late is
            # metered too. An admitted tool that is not counted would be exactly
            # the unbounded surface this budget exists to retire.
            _install_call_budget(
                self.admission.server_names,
                self.call_budget,
                on_exhausted=self.on_budget_exhausted,
            )
        except Exception as exc:  # pragma: no cover - defensive; surfaced as a typed denial
            self.box["error"] = exc
            logger.warning("MCP admission registration failed: %s", exc, exc_info=True)
        finally:
            # The WORKER releases the mutex, never the caller: on a timeout the
            # caller returns while this registration is still connecting, and
            # releasing here is what keeps a second admission from interleaving
            # against the global registry mid-spawn.
            _ADMISSION_LOCK.release()
            self.done.set()

    def register_bounded(self) -> bool | None:
        """Run the registrar on its worker; True when it finished inside the budget.

        ``None`` when the worker could not even start — the mutex is released
        here then, because no worker exists to release it.
        """

        worker = threading.Thread(target=self._work, name="mcp-admission", daemon=True)
        try:
            worker.start()
        except Exception:  # pragma: no cover - thread exhaustion; never strand the mutex
            _ADMISSION_LOCK.release()
            logger.warning("MCP admission could not start its registration thread", exc_info=True)
            return None
        return self.done.wait(self.budget)

    def timed_out(self, duration_ms: int) -> McpAdmissionOutcome:
        budget = self.budget
        timed_out = tuple(
            McpAdmissionDenial(
                server=name,
                code=MCP_ADMISSION_TIMEOUT,
                summary=(
                    f"'{name}' did not finish registering within {budget:.0f}s, so it is "
                    "not available for this turn."
                ),
                fix_hint=(
                    "The turn continues without it and there is no harness-side contract "
                    "to take instead — report that plainly and finish without it rather "
                    "than improvising a second lane. If the "
                    "server is slow to start, start it before the turn rather than raising "
                    "agent_runtime.mcp_admission.connect_timeout_seconds into the turn budget."
                ),
            )
            for name in self.admission.server_names
        )
        return McpAdmissionOutcome(
            attempted=True,
            duration_ms=duration_ms,
            denied=tuple(self.admission.denied) + timed_out,
            execution_denied=timed_out,
            # The meter is already armed and the worker will install it if the
            # registration lands late, so the run stays bounded even on the path
            # where the caller gave up on it.
            call_budget=self.call_budget,
            # A timeout is almost always a COLD spawn that outran the budget, and
            # saying so is the difference between "MCP is slow" and "that server
            # takes longer to start than the turn allows".
            transport_paths=self.transport_paths,
        )

    def outcome(self, duration_ms: int) -> McpAdmissionOutcome:
        from ..mcp_lane import registered_mcp_server_names

        registered = registered_mcp_server_names()
        names = self.admission.server_names
        missed = tuple(name for name in names if name not in registered)
        # WHY nothing registered, before WHICH server did not. A runtime with no MCP
        # client registers nothing for every server at once, and saying "the server
        # did not connect" of a server nothing ever tried to reach is the sentence
        # that cost weeks (see MCP_SDK_UNAVAILABLE). Read only on the production
        # path: a caller-supplied ``register`` is not the SDK's registrar, so the
        # flag says nothing about what it did.
        sdk_missing = bool(missed) and self.register is None and not mcp_sdk_available()
        unregistered = tuple(_unregistered_denial(name, sdk_missing=sdk_missing) for name in missed)
        return McpAdmissionOutcome(
            attempted=True,
            admitted=tuple(name for name in names if name in registered),
            duration_ms=duration_ms,
            denied=tuple(self.admission.denied) + unregistered,
            execution_denied=unregistered,
            call_budget=self.call_budget,
            transport_paths=self.transport_paths,
        )


def _unregistered_denial(name: str, *, sdk_missing: bool) -> McpAdmissionDenial:
    """The typed row for an admitted server that did not register."""

    if sdk_missing:
        return McpAdmissionDenial(
            server=name,
            code=MCP_SDK_UNAVAILABLE,
            summary=(
                f"'{name}' registered nothing because this hermes runtime has no MCP "
                "client installed — not because the server is unavailable."
            ),
            fix_hint=(
                "Install the optional MCP client into the runtime's venv "
                '(pip install "hermes-agent[mcp]" — the `mcp` extra in pyproject.toml) '
                "and then RESTART the hermes runtime: availability is read once at "
                "import, so an install does not reach a running process. Nothing about "
                "the server, its command or its declaration needs changing."
            ),
        )
    return McpAdmissionDenial(
        server=name,
        code=MCP_NOT_REGISTERED_ON_LANE,
        summary=(
            f"'{name}' was admitted for this run but did not register — the server "
            "did not connect or advertised no tools."
        ),
        fix_hint=(
            "Check the server is running and its command resolves on this machine "
            "(hermes harness persona tool-diff <persona> --explain-mcp), then retry."
        ),
    )


# ── the per-run call budget's counting seam ─────────────────────────────────
#
# The count is taken at DISPATCH, over exactly the tools this run's admission
# registered. That is the only place where "an admitted MCP call happened" is a
# fact rather than an inference: the tool list is not the control surface here
# (a model can call an advertised tool any number of times), and the runner's
# tool-start progress hook can only OBSERVE — it has no refuse path that does
# not also end the turn, which §7 does not ask for and §3's threat model does
# not want (an agent that loses the launcher should still be able to write up
# what it saw).
#
# Mechanically: ``registry.dispatch`` reads ``entry.handler`` per call, so
# replacing that attribute with a metered wrapper is a complete interception —
# no upstream edit, no parallel dispatch path, and the wrapper dies with the
# registry scope at teardown.

#: Attribute the wrapper stashes the original handler under. Also the marker
#: that answers "is this handler already metered?", which is what keeps a
#: re-admission after a FAILED teardown from stacking two meters on one tool.
_UNMETERED_HANDLER_ATTR = "_mcp_admission_unmetered_handler"


def _install_call_budget(
    servers: Iterable[str],
    budget: "McpCallBudget",
    *,
    on_exhausted: Callable[[McpAdmissionDenial, dict[str, Any]], None] | None = None,
) -> list[str]:
    """Meter every registered tool of the admitted servers. Fails CLOSED.

    A tool that cannot be metered is DEREGISTERED rather than left callable:
    an unbounded admitted tool is the exact exposure the budget exists to close,
    and removing it degrades into surfaces that already exist — if that empties
    the server's scope, the caller's registry read reports the server as
    ``mcp_not_registered_on_lane`` and the turn takes the fallback lane.

    Returns the prefixed names it could not meter (and therefore removed).
    """

    names = [str(name).strip() for name in servers or () if str(name or "").strip()]
    if not names:
        return []
    try:
        from tools.registry import registry
    except Exception:  # pragma: no cover - registry is always importable in-process
        logger.warning(
            "MCP admission could not reach the tool registry to install the per-run "
            "call budget; the admitted tools are not metered",
            exc_info=True,
        )
        return []

    unmetered: list[str] = []
    for server in names:
        toolset = f"{_MCP_TOOLSET_PREFIX}{server}"
        try:
            tool_names = list(registry.get_tool_names_for_toolset(toolset) or [])
        except Exception:  # pragma: no cover - defensive
            logger.warning("MCP admission could not list %r for metering", toolset, exc_info=True)
            continue
        for tool_name in tool_names:
            if _meter_registered_tool(
                registry, server, tool_name, budget, on_exhausted=on_exhausted
            ):
                continue
            unmetered.append(tool_name)
            try:
                registry.deregister(tool_name)
            except Exception:  # pragma: no cover - defensive
                logger.error(
                    "MCP admission could neither meter nor remove %r; it is admitted "
                    "WITHOUT a per-run call bound",
                    tool_name,
                    exc_info=True,
                )
    if unmetered:
        logger.warning(
            "MCP admission removed %d admitted tool(s) it could not meter: %s",
            len(unmetered),
            ", ".join(sorted(unmetered)),
        )
    return unmetered


def _meter_registered_tool(
    registry: Any,
    server: str,
    tool_name: str,
    budget: "McpCallBudget",
    *,
    on_exhausted: Callable[[McpAdmissionDenial, dict[str, Any]], None] | None = None,
) -> bool:
    """Swap one registered tool's handler for a budget-metered one."""

    try:
        entry = registry.get_entry(tool_name)
        if entry is None:  # pragma: no cover - raced against a deregister
            return False
        handler = getattr(entry, "handler", None)
        if not callable(handler):
            return False
        if getattr(entry, "is_async", False):
            # Upstream registers every MCP tool with ``is_async=False`` (the
            # handler bridges to the MCP loop itself), and the refusal path
            # returns a STRING — which an async entry's dispatch would try to
            # await. Rather than guess at a coroutine shape we do not need, an
            # async admitted tool is left unmetered ⇒ removed by the caller.
            # Pinned by a drift test, so upstream changing this is loud.
            logger.warning(
                "MCP admission cannot meter async tool %r; it will not be admitted",
                tool_name,
            )
            return False
        # Unwrap first: a re-admission after a teardown that FAILED would
        # otherwise meter a meter, and the outer one's budget would be the only
        # one anybody could read.
        base = getattr(handler, _UNMETERED_HANDLER_ATTR, handler)
        entry.handler = _metered_handler(
            base, server=server, tool_name=tool_name, budget=budget, on_exhausted=on_exhausted
        )
        return True
    except Exception:
        logger.warning("MCP admission could not meter %r", tool_name, exc_info=True)
        return False


def _metered_handler(
    handler: Callable[..., Any],
    *,
    server: str,
    tool_name: str,
    budget: "McpCallBudget",
    on_exhausted: Callable[[McpAdmissionDenial, dict[str, Any]], None] | None = None,
) -> Callable[..., Any]:
    """``handler(args, **kwargs) -> str``, charged against the run's call budget.

    On exhaustion it returns the typed row INSTEAD of dispatching, in the same
    ``{"error": ...}`` JSON envelope the MCP handlers already return for their
    circuit breaker — so the model reads it as a normal tool refusal with a
    reason, the turn keeps running, and the agent can still write up what it has.
    """

    def _metered(*args: Any, **kwargs: Any) -> Any:
        denial = budget.consume(server, tool_name)
        if denial is None:
            return handler(*args, **kwargs)
        snapshot = budget.snapshot()
        first = snapshot.get("refused") == 1
        if first and on_exhausted is not None:
            try:
                on_exhausted(denial, snapshot)
            except Exception:  # pragma: no cover - a notification must never fail a tool
                logger.debug("MCP admission budget notification failed", exc_info=True)
        # The first refusal is the event; the rest are the loop it exists to
        # bound, and a looping agent must not be able to flood agent.log.
        logger.log(
            logging.WARNING if first else logging.DEBUG,
            "MCP admission budget exhausted (%d/%d, %d refused): refused %r",
            snapshot.get("spent"),
            snapshot.get("limit"),
            snapshot.get("refused"),
            tool_name,
        )
        payload = dict(denial.row())
        payload["error"] = denial.summary
        payload["tool"] = tool_name
        payload["budget"] = snapshot
        return json.dumps(payload, ensure_ascii=False)

    setattr(_metered, _UNMETERED_HANDLER_ATTR, handler)
    return _metered


def teardown_mcp_admission(
    servers: Iterable[str] | None,
    *,
    lock_timeout_seconds: float = 5.0,
) -> McpTeardownOutcome:
    """Remove an admitted run's registry scope. Keeps the transport warm.

    Deregisters every tool in each admitted ``mcp-<server>`` toolset.
    ``registry.deregister`` exempts ``mcp-*`` from the plugin-ownership gate, and
    dropping the LAST tool of a toolset also drops its toolset check and every
    alias pointing at it — so both spellings a run could have resolved
    (``mcp-launcher_qa`` and the bare ``launcher_qa`` alias) go with it.

    The transport is deliberately untouched: ``tools/mcp_tool._servers`` keeps the
    connection, so the next admitted run re-registers off the live session
    instead of paying a fresh spawn + handshake. Process exit still owns the
    connections (``tools.mcp_tool.shutdown_mcp_servers``).

    Only ever called with servers THIS run admitted, and admission only ever runs
    on the harness lane (``persona_runtime.mission_chat_reply`` is the sole
    producer of ``AgentRunRequest.mcp_admission``), so this can never remove a
    scope that an MCP-registering entry point's ``discover_mcp_tools()`` created.

    Never raises. Every fault becomes a typed ``mcp_admission_teardown_failed``
    row: a finished turn must never be failed by its own cleanup.
    """

    names = [str(name).strip() for name in servers or () if str(name or "").strip()]
    started = time.perf_counter()
    if not names:
        return McpTeardownOutcome()

    failures: list[McpAdmissionDenial] = []
    # A registration whose CALLER timed out keeps running on its worker thread
    # (that is why the worker, not the caller, releases the mutex). Waiting for
    # it here is what stops teardown from racing a late registration and leaving
    # exactly the residue it exists to remove.
    held = _ADMISSION_LOCK.acquire(timeout=max(0.0, float(lock_timeout_seconds)))
    if not held:
        failures.append(
            McpAdmissionDenial(
                server=", ".join(names),
                code=MCP_ADMISSION_TEARDOWN_FAILED,
                summary=(
                    "An MCP admission was still in flight when this run's scope was torn "
                    "down; the scope was removed anyway and a late registration may have "
                    "re-added tools."
                ),
                fix_hint=(
                    "Bounded by agent_runtime.mcp_admission.connect_timeout_seconds. The "
                    "next run's toolset scope still refuses any MCP toolset it was not "
                    "admitted, so this is residue, not exposure."
                ),
            )
        )
    try:
        removed = _deregister_toolset_scopes(names, failures)
    finally:
        if held:
            _ADMISSION_LOCK.release()

    return McpTeardownOutcome(
        servers=tuple(names),
        removed_tool_names=tuple(removed),
        failures=tuple(failures),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _deregister_toolset_scopes(
    names: Sequence[str], failures: list[McpAdmissionDenial]
) -> list[str]:
    """Registry-only scope removal. Never imports ``tools.mcp_tool`` (SDK)."""

    try:
        from tools.registry import registry
    except Exception:  # pragma: no cover - registry is always importable in-process
        failures.append(
            McpAdmissionDenial(
                server=", ".join(names),
                code=MCP_ADMISSION_TEARDOWN_FAILED,
                summary="The tool registry was unavailable, so no admitted MCP scope was removed.",
                fix_hint="The next run's toolset scope still refuses un-admitted MCP toolsets.",
            )
        )
        return []

    removed: list[str] = []
    for name in names:
        toolset = f"{_MCP_TOOLSET_PREFIX}{name}"
        try:
            for tool_name in list(registry.get_tool_names_for_toolset(toolset) or []):
                registry.deregister(tool_name)
                removed.append(tool_name)
        except Exception as exc:
            logger.warning("MCP admission teardown failed for %r: %s", name, exc, exc_info=True)
            failures.append(
                McpAdmissionDenial(
                    server=name,
                    code=MCP_ADMISSION_TEARDOWN_FAILED,
                    summary=(
                        f"'{name}' tools could not be deregistered after the run "
                        f"({type(exc).__name__}), so its registry scope outlived it."
                    ),
                    fix_hint=(
                        "Isolation falls back to the per-run toolset scope until the process "
                        "recycles. Check tools/registry.py deregister for this toolset."
                    ),
                )
            )
    return removed
