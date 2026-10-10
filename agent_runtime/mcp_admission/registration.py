"""The registry scope's two ends (invariants 4-6): ``admit_mcp_servers`` under
the single-flight mutex with its per-run call budget, ``release_mcp_admission``
(the end of every admitted run: the budget is unbound, the resident scope kept),
and ``teardown_mcp_admission`` (the scope removed)."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from .vocabulary import MCP_NOT_REGISTERED_ON_LANE
from ..serde import positive_float

from .outcomes import McpAdmission, McpAdmissionDenial, McpAdmissionOutcome, McpCallBudget, McpTeardownOutcome
from . import resident
from .resident import SLOT_ATTR, BudgetSlot, ResidentScope
from .transport import _default_registrar, classify_admission_transport, mcp_sdk_available
from .vocabulary import MCP_ADMISSION_BUDGET_EXHAUSTED, MCP_ADMISSION_LANE_BUSY, MCP_CLIENT_DISABLED, MCP_ADMISSION_TEARDOWN_FAILED, MCP_ADMISSION_TIMEOUT, MCP_SDK_UNAVAILABLE, _MCP_TOOLSET_PREFIX, logger

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
    abandon: Callable[[], Any] | None = None,
) -> McpAdmissionOutcome:
    """Register the admitted servers' tools for this run. Bounded, single-flight.

    ``abandon`` (h-turn-wait; a prewarm's yield gauge) is polled while the caller
    waits: a truthy answer stops the WAIT early and the outcome reads as a timeout
    (the registrar keeps running, as it does past the budget). A prewarm waits here
    inside ``_WORKDIR_LOCK``; a turn behind it must not wait out a 20 s spawn.

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
    if register is None and not _mcp_client_enabled():
        return _client_disabled_outcome(admission)
    return Admission(
        admission,
        register=register,
        timeout_seconds=timeout_seconds,
        on_budget_exhausted=on_budget_exhausted,
        abandon=abandon,
    ).run()


#: How often a waiting admission asks its ``abandon`` gauge (h-turn-wait): the most a
#: turn waits on a prewarm parked here, beyond the unwind.
_ABANDON_POLL_SECONDS = 0.05


def _mcp_client_enabled() -> bool:
    """Config ``mcp.client``, asked BEFORE anything imports the client runtime.

    Its reader lives in ``tools.mcp_tool_common``, which every distribution ships;
    ``tools.mcp_tool`` and its client siblings are what a build with the switch
    off omits. Asked only on the production path: a caller-supplied ``register``
    is not the client, so the switch says nothing about it (the SDK flag's rule)."""

    from tools.mcp_tool_common import mcp_client_enabled

    return mcp_client_enabled()


def _client_disabled_outcome(admission: McpAdmission) -> McpAdmissionOutcome:
    """Every admitted server denied with ``mcp_client_disabled``; nothing imported."""

    disabled = tuple(
        McpAdmissionDenial(
            server=name,
            code=MCP_CLIENT_DISABLED,
            summary=(
                f"'{name}' was not registered because this hermes distribution runs no "
                "MCP client (config mcp.client is off) — not because the server is unavailable."
            ),
            fix_hint=(
                "This build deliberately ships without the MCP client, so installing a "
                "package will not help. Finish the turn without the server and say what "
                "went unverified; an operator can run the persona on a distribution with "
                "mcp.client on."
            ),
        )
        for name in admission.server_names
    )
    return McpAdmissionOutcome(
        attempted=True,
        denied=tuple(admission.denied) + disabled,
        execution_denied=disabled,
    )


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
        abandon: Callable[[], Any] | None = None,
    ) -> None:
        self.admission = admission
        self.register = register
        self.on_budget_exhausted = on_budget_exhausted
        self.abandon = abandon
        self.budget = positive_float(timeout_seconds) or admission.connect_timeout_seconds
        self.servers = dict(admission.server_configs)
        self.started = time.perf_counter()
        self.done = threading.Event()
        self.box: dict[str, Any] = {}
        self.transport_paths: dict[str, str] = {}
        #: Servers whose resident scope this admission reused (no registrar, no generation move).
        self.reused: tuple[str, ...] = ()
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
            # D1.01: a server whose resident scope still stands for this admission is not
            # re-registered; only the rest reach the registrar.
            reused, fresh = resident.partition_admission(self.servers)
            self.reused = tuple(name for name in self.admission.server_names if name in reused)
            if fresh:
                registrar = self.register or _default_registrar
                self.box["tools"] = registrar(dict(fresh))
            # Meter INSIDE the worker, still holding the admission mutex, so a
            # registration that outran the caller's timeout and lands late is
            # metered too. An admitted tool that is not counted would be exactly
            # the unbounded surface this budget exists to retire.
            _bind_call_budget(
                self.admission.server_names,
                self.servers,
                reused,
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
        if self.abandon is None:
            return self.done.wait(self.budget)
        deadline = time.perf_counter() + self.budget
        while not self.done.wait(min(_ABANDON_POLL_SECONDS, max(0.0, deadline - time.perf_counter()))):
            if time.perf_counter() >= deadline or self.abandon():
                return False
        return True

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
# no upstream edit, no parallel dispatch path. Since D1.01 the wrapper lives as
# long as the resident scope and reads the run's budget from the scope's
# :class:`~.resident.BudgetSlot` at call time, so binding a run's budget is an
# attribute write, never a registration (no ``registry.generation`` move).

#: Attribute the wrapper stashes the original handler under. Also the marker
#: that answers "is this handler already metered?", which is what keeps a
#: re-admission after a FAILED teardown from stacking two meters on one tool.
_UNMETERED_HANDLER_ATTR = "_mcp_admission_unmetered_handler"


def _bind_call_budget(
    servers: Iterable[str],
    configs: Mapping[str, Mapping[str, Any]],
    reused: Mapping[str, ResidentScope],
    budget: "McpCallBudget",
    *,
    on_exhausted: Callable[[McpAdmissionDenial, dict[str, Any]], None] | None = None,
) -> list[str]:
    """Bind this run's budget to every admitted server's scope. Fails CLOSED.

    A reused (resident) scope gets the budget written into its slot. A freshly
    registered one gets a new slot, every tool metered against it, and is
    remembered as resident. A tool that cannot be metered is DEREGISTERED rather
    than left callable: an unbounded admitted tool is the exact exposure the
    budget exists to close, and removing it degrades into surfaces that already
    exist — if that empties the server's scope, the caller's registry read
    reports the server as ``mcp_not_registered_on_lane``.

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
        scope = reused.get(server)
        if scope is not None:
            scope.slot.bind(budget, on_exhausted)
            continue
        slot = BudgetSlot()
        slot.bind(budget, on_exhausted)
        unmetered.extend(_meter_server(registry, server, slot))
        resident.record_resident_scope(server, configs.get(server), slot)
    if unmetered:
        logger.warning(
            "MCP admission removed %d admitted tool(s) it could not meter: %s",
            len(unmetered),
            ", ".join(sorted(unmetered)),
        )
    return unmetered


def _meter_server(registry: Any, server: str, slot: BudgetSlot) -> list[str]:
    """Meter every registered tool of ``mcp-<server>`` against ``slot``; remove the rest."""

    toolset = f"{_MCP_TOOLSET_PREFIX}{server}"
    try:
        tool_names = list(registry.get_tool_names_for_toolset(toolset) or [])
    except Exception:  # pragma: no cover - defensive
        logger.warning("MCP admission could not list %r for metering", toolset, exc_info=True)
        return []
    unmetered: list[str] = []
    for tool_name in tool_names:
        if _meter_registered_tool(registry, server, tool_name, slot):
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
    return unmetered


def _meter_registered_tool(registry: Any, server: str, tool_name: str, slot: BudgetSlot) -> bool:
    """Swap one registered tool's handler for a slot-metered one."""

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
        entry.handler = _metered_handler(base, server=server, tool_name=tool_name, slot=slot)
        return True
    except Exception:
        logger.warning("MCP admission could not meter %r", tool_name, exc_info=True)
        return False


def _unbound_denial(server: str, tool_name: str) -> McpAdmissionDenial:
    """The refusal for a resident tool dispatched while no admitted run holds its budget."""

    return McpAdmissionDenial(
        server=server,
        code=MCP_ADMISSION_BUDGET_EXHAUSTED,
        summary=(
            f"'{tool_name}' was refused: no admitted run holds a call budget for "
            f"'{server}' right now, so it has no calls to spend."
        ),
        fix_hint=(
            "Only a run that admitted the server may call its tools. Finish without it "
            "and say what went unverified."
        ),
    )


def _metered_handler(
    handler: Callable[..., Any],
    *,
    server: str,
    tool_name: str,
    slot: BudgetSlot,
) -> Callable[..., Any]:
    """``handler(args, **kwargs) -> str``, charged against the bound run's call budget.

    On exhaustion it returns the typed row INSTEAD of dispatching, in the same
    ``{"error": ...}`` JSON envelope the MCP handlers already return for their
    circuit breaker — so the model reads it as a normal tool refusal with a
    reason, the turn keeps running, and the agent can still write up what it has.
    An empty slot (no admitted run) refuses every call: the fail-closed direction.
    """

    def _metered(*args: Any, **kwargs: Any) -> Any:
        budget, on_exhausted = slot.current()
        if budget is None:
            denial = _unbound_denial(server, tool_name)
            payload = dict(denial.row())
            payload["error"] = denial.summary
            payload["tool"] = tool_name
            return json.dumps(payload, ensure_ascii=False)
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
    setattr(_metered, SLOT_ATTR, slot)
    return _metered


def release_mcp_admission(
    servers: Iterable[str] | None,
    *,
    lock_timeout_seconds: float = 5.0,
) -> McpTeardownOutcome:
    """The end of an admitted run: unbind its call budget, KEEP the resident scope.

    D1.01 (owner ruling 2026-10-10, superseding R2's per-run teardown): the scope
    lives for the transport session plus the admission content; isolation is
    ``scope_toolsets_to_admission``. So the registry is left exactly as the run
    found it (``registry.generation`` unmoved) and the next admitting run binds
    its own budget into the same slot.

    Never raises. Every fault becomes a typed ``mcp_admission_teardown_failed``
    row: a finished turn must never be failed by its own cleanup.
    """

    names = [str(name).strip() for name in servers or () if str(name or "").strip()]
    started = time.perf_counter()
    if not names:
        return McpTeardownOutcome()
    failures: list[McpAdmissionDenial] = []
    removed: list[str] = []
    # A registration whose CALLER timed out keeps running on its worker thread;
    # waiting for it here keeps its late bind from landing after this release.
    held = _ADMISSION_LOCK.acquire(timeout=max(0.0, float(lock_timeout_seconds)))
    if not held:
        failures.append(_in_flight_denial(names))
    try:
        # Only a scope that no longer stands is deregistered (session gone or
        # replaced, a tool lost); a valid one is kept with its slot cleared.
        removed = resident.release_slots(names)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("MCP admission release failed: %s", exc, exc_info=True)
        failures.append(_registry_fault_denial(", ".join(names), exc))
    finally:
        if held:
            _ADMISSION_LOCK.release()
    return McpTeardownOutcome(
        servers=tuple(names),
        removed_tool_names=tuple(removed),
        failures=tuple(failures),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def drop_resident_scopes(
    servers: Iterable[str] | None = None,
    *,
    lock_timeout_seconds: float = 5.0,
) -> McpTeardownOutcome:
    """Retire resident scopes explicitly: ``servers``, or every one in the current home.

    The registry tools go and the memo forgets them; the transport stays (process exit
    owns connections, ``tools.mcp_tool.shutdown_mcp_servers``). Never raises.
    """

    names = resident.resident_server_names() if servers is None else servers
    return teardown_mcp_admission(names, lock_timeout_seconds=lock_timeout_seconds)


def _in_flight_denial(names: Sequence[str]) -> McpAdmissionDenial:
    return McpAdmissionDenial(
        server=", ".join(names),
        code=MCP_ADMISSION_TEARDOWN_FAILED,
        summary=(
            "An MCP admission was still in flight when this run's scope was released; "
            "a late registration may bind its budget after the release."
        ),
        fix_hint=(
            "Bounded by agent_runtime.mcp_admission.connect_timeout_seconds. The "
            "next run's toolset scope still refuses any MCP toolset it was not "
            "admitted, so this is residue, not exposure."
        ),
    )


def _registry_fault_denial(server: str, exc: BaseException) -> McpAdmissionDenial:
    return McpAdmissionDenial(
        server=server,
        code=MCP_ADMISSION_TEARDOWN_FAILED,
        summary=(
            f"'{server}' scope could not be released after the run "
            f"({type(exc).__name__}), so its registry scope outlived it unchanged."
        ),
        fix_hint=(
            "Isolation falls back to the per-run toolset scope until the process "
            "recycles. Check tools/registry.py deregister for this toolset."
        ),
    )


def teardown_mcp_admission(
    servers: Iterable[str] | None,
    *,
    lock_timeout_seconds: float = 5.0,
) -> McpTeardownOutcome:
    """Remove an admitted server's resident registry scope. Keeps the transport warm.

    Not the end of a run any more (that is :func:`release_mcp_admission`, D1.01):
    this is the explicit retirement verb, and it forgets the resident memo for
    the servers it removes. Deregisters every tool in each admitted ``mcp-<server>`` toolset.
    ``registry.deregister`` exempts ``mcp-*`` from the plugin-ownership gate, and
    dropping the LAST tool of a toolset also drops its toolset check and every
    alias pointing at it — so both spellings a run could have resolved
    (``mcp-launcher_qa`` and the bare ``launcher_qa`` alias) go with it.

    The transport is deliberately untouched: ``tools/mcp_tool._servers`` keeps the
    connection, so the next admitted run re-registers off the live session
    instead of paying a fresh spawn + handshake. Process exit still owns the
    connections (``tools.mcp_tool.shutdown_mcp_servers``).

    Only ever called with servers an admission registered, and admission only ever runs
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
        resident.forget(names)
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
        try:
            removed.extend(resident.deregister_server_tools(name, registry))
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
