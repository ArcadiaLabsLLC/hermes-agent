"""The three durable phases one reservation covers, and their read-back:
the placement payload and slot policy, the skills phase (install, verify,
resolve, assign — in that order), the reply builder that re-reads the
actor, and the compensation that retires a roster row whose placement did
not land.
"""

from __future__ import annotations

from typing import Any

from .outcome import ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, AgentCreateSkillsRefused
from .request import AgentCreateRequest

__layer__ = "stores"


def placement_actor_payload(
    request: AgentCreateRequest,
    *,
    display_name: str,
    position: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """The actor payload for a freshly minted placement.

    ``position`` is the operator's AIM, and ``None`` means they had none. A
    payload built without one carries no ``position`` key at all, and the store
    is then required to receive :func:`placement_position_policy` beside it —
    ``OfficeStore.upsert_actor`` resolves the slot under its own lock (M10) and
    refuses a positionless item outright when no policy came with it, so the
    pairing is enforced by the store rather than by convention here.

    Deliberately NOT filled with a stand-in when the aim is absent. A payload
    with a made-up origin would place an agent at ``(0, 0)`` and read as a
    deliberate placement forever, and once such a value exists it only has to
    survive one refactor to escape; a MISSING key cannot.

    Deliberately the SAME shape ``harness office actor-upsert`` takes on
    ``--actor-json`` and the launcher's ``officeActorPayloadsFromLayout``
    produces — one schema across three writers, so a lane switch can never read
    as an edit. It is instance-keyed by construction (``persona_instance_id``
    is the id the mint just returned), which is what makes the class-key
    collision the office fence exists to refuse unreachable from this method.
    """

    item: dict[str, Any] = {
        "item_id": request.persona_instance_id,
        "persona_id": request.persona_id,
        "kind": "agent",
        "folder": request.folder,
        "display_name": display_name,
    }
    if position is not None:
        x, y = position
        item["position"] = [x, y]
    return {
        "persona_id": request.persona_id,
        "persona_instance_id": request.persona_instance_id,
        "items": [item],
    }


def placement_slot_for(
    actors: Any, request: AgentCreateRequest
) -> tuple[float, float]:
    """The slot an UNAIMED create lands on (plan D2), given the floor it lands on.

    PURE — ``actors`` in, point out, no store and no clock — so the decision
    table is unit-testable directly and the caller decides which actor set to
    feed it. The store-facing half is :func:`placement_position_policy`.

    Scans the actors in the REQUEST's folder and returns the first free lattice
    slot. The lane is the AGENT lane whatever the folder is called, because this
    verb writes exactly one ``kind: "agent"`` item and nothing else (D6) — the
    desk lane's diagonal nudge exists to keep unaimed desks off the agent
    lattice, and there are no unaimed desks on this lane.

    The actor this create is about to write is excluded here rather than by the
    store. A resumed attempt (``instance_minted`` receipt, placement already
    landed, ``mark_done`` never reached) would otherwise read its OWN previous
    item as a blocker and move the agent one slot along on every retry — an
    idempotent replay that walks. The store hands over the whole live set
    because it cannot know which row is "mine"; this lane can, and does.
    """

    from ..office_layout_policy import (
        lane_offset_for_kind,
        next_free_slot,
        occupied_positions,
    )

    mine = request.persona_instance_id
    others = [
        actor
        for actor in actors or ()
        if getattr(actor, "persona_instance_id", None) != mine
    ]
    return next_free_slot(
        occupied_positions(others, folder=request.folder),
        lane_offset=lane_offset_for_kind("agent"),
    )


def placement_position_policy(request: AgentCreateRequest):
    """The hook ``OfficeStore.upsert_actor`` calls INSIDE ``office_lock``.

    WHERE THIS READ SITS RELATIVE TO ``office_lock``, AND WHY
    --------------------------------------------------------
    INSIDE it, as of H-H10. The store takes ``office_lock(workspace_id)``,
    scans the workspace, calls this, and writes — one acquisition across the
    read and the write, which is what closes M10: two creates that both omit a
    position can no longer compute the same free slot, because the second
    cannot scan until the first has written.

    It used to sit OUTSIDE, resolved by the caller and sent as an ordinary
    position, and that was forced rather than preferred: ``locks._file_lock`` is
    a real file lock held through a fresh ``open()`` per acquisition, so it is
    NOT reentrant, and wrapping the caller's read in a second ``office_lock``
    would have deadlocked the write it was meant to protect. The honest close
    was always "move the policy into the store", and that is what this is — the
    store supplies the SET and the lock, this supplies the arithmetic
    (:func:`placement_slot_for`) and the exclusion rule.

    THE SHORTFALL, named because the parameter type makes it askable. The store
    hands over the whole :class:`ActorScan`, so an incomplete floor is visible
    here. This lane proceeds on ``scan.actors`` anyway: an unreadable neighbour
    can at worst cost this placement one slot of overlap, which is the bounded,
    draggable, canvas-visible outcome the old cross-process race had — while
    refusing the create would cost the operator their agent over a file that has
    nothing to do with it. That is a choice this policy makes and states, not a
    fact the seam hides.
    """

    def _policy(scan) -> tuple[float, float]:
        return placement_slot_for(scan.actors, request)

    return _policy


def run_skills_phase(
    skills: Any,
    *,
    instance_id: str,
    requested_by: str = "runtime.agent.create",
) -> dict[str, Any]:
    """Install, verify, resolve, then assign — in that order, each for a reason.

    Returns the ack block ``{assigned, installed}``; raises
    :class:`AgentCreateSkillsRefused` on every refusal.

    **Every id must survive BOTH sanitizers unchanged before any root is
    walked.** ``safe_id`` is D5's named gate; ``safe_assignment_token`` is the
    one the persona-instance store applies on the way in
    (``_safe_skill_overrides``), and it is the stricter of the two — it maps
    ``:`` to ``_`` where ``safe_id`` keeps it. Requiring identity under both is
    what makes the ack's ``assigned`` list the list the store actually HOLDS
    rather than a request the store quietly re-spelled, and it is also what
    makes "never path-joined from input" true: no separator, no drive letter and
    no leading dot survives either function, so the name handed to
    ``resolve_skills`` cannot address anything outside a skills root.

    **Install BEFORE resolve, deliberately.** D5 lists the resolve gate first
    and the install gate second, and the code runs them the other way round
    because a canonical skill's resolvable copy IS the installed one: on a
    machine where the shared root has never been written, resolving first would
    refuse ``skill_unresolved: missing`` for a skill the very next line would
    have installed. Resolving AFTER the install asks the question of the world
    the assignment will actually run against.

    **Assign LAST.** Nothing writes ``skill_overrides`` until every id has both
    gates behind it, so a two-skill request cannot leave one assigned and the
    other refused.

    **What a refusal here does NOT do.** It does not compensate the placement.
    That is D4 and it is not a convenience: a placed agent without its skills is
    the state every launcher drop produces today — valid, visible, messageable —
    and retiring it to satisfy atomicity would archive a working agent to undo a
    file copy. The reservation is already at ``placed`` when this runs, so the
    same idempotency key resumes here and nowhere else.
    """

    return SkillsPhase(skills, instance_id=instance_id, requested_by=requested_by).run()


class SkillsPhase:
    """The skills phase as its three gates and one write, in the order D5 needs.

    ``gate_spelling -> gate_installed -> gate_resolved -> write``; the method
    order IS the order the comments insist on, and every refusal is raised
    where it is decided (:class:`AgentCreateSkillsRefused`), never rendered here.
    """

    def __init__(self, skills: Any, *, instance_id: str, requested_by: str) -> None:
        self.ids = [str(item) for item in (skills or ())]
        self.instance_id = instance_id
        self.requested_by = requested_by

    def run(self) -> dict[str, Any]:
        self.gate_spelling()
        installed = self.gate_installed()
        self.gate_resolved()
        return self.write(installed)

    def gate_spelling(self) -> None:
        """Gate 0 — the spelling, asked before any root is walked."""

        from ..persona_assignments import safe_assignment_token
        from ..serde import safe_id

        for identifier in self.ids:
            if (
                safe_id(identifier) != identifier
                or safe_assignment_token(identifier) != identifier
            ):
                raise AgentCreateSkillsRefused(
                    ERR_INVALID_PARAMS,
                    f"skill id cannot be resolved: {identifier!r}",
                    {
                        "reason": "skill_unresolved",
                        "skill": identifier,
                        # ``missing`` and not a fourth status: the resolver's own
                        # vocabulary is {missing, collision, invalid_source} and a
                        # name no skill root can hold is missing from all of them.
                        "status": "missing",
                    },
                )

    def gate_installed(self) -> list[dict[str, Any]]:
        """Gate 1 — the canonical ids are installed and PROVEN hash-equal."""

        from agent_runtime.profile_home import CANONICAL_SHARED_SKILL_IDS

        installed: list[dict[str, Any]] = []
        for identifier in self.ids:
            if identifier not in CANONICAL_SHARED_SKILL_IDS:
                # A non-canonical id has no repo package to compare against, so
                # there is nothing to install and nothing to verify — it is
                # answered by the resolver alone.
                continue
            installed.append(self._install(identifier))
        return installed

    def _install(self, identifier: str) -> dict[str, Any]:
        from ..skill_install import (
            HarnessSkillInstallDiverged,
            install_and_verify_harness_skill,
        )

        try:
            receipt = install_and_verify_harness_skill(identifier)
        except HarnessSkillInstallDiverged as exc:
            raise AgentCreateSkillsRefused(
                ERR_HANDLER_FAILED,
                str(exc),
                {
                    "reason": "skill_install_diverged",
                    "skill": exc.skill,
                    "source_hash": exc.source_hash,
                    "installed_hash": exc.installed_hash,
                },
            ) from exc
        except Exception as exc:  # noqa: BLE001 - a copy fault IS a divergence
            # The staged ``copytree``/``os.replace`` can fail for a dozen OS
            # reasons, and every one of them ends the same way: the installed
            # bytes are not known to match the repo's. Answering that with a
            # traceback out of the RPC boundary would strand a placed agent
            # behind a -32000 with no ``data`` at all, so it renders as the
            # divergence it is, with the hashes it could not establish left
            # explicitly null rather than guessed.
            raise AgentCreateSkillsRefused(
                ERR_HANDLER_FAILED,
                f"skill install failed: {identifier}: {type(exc).__name__}: {exc}",
                {
                    "reason": "skill_install_diverged",
                    "skill": identifier,
                    "source_hash": None,
                    "installed_hash": None,
                },
            ) from exc
        return {
            "skill": receipt.skill,
            "changed": bool(receipt.changed),
            "installed_hash": receipt.installed_hash,
        }

    def gate_resolved(self) -> None:
        """Gate 2 — every id resolves, in the runtime this create is answering out of."""

        if not self.ids:
            return
        from agent_runtime.skill_resolution import resolve_skills

        resolutions = resolve_skills(list(self.ids))
        for identifier in self.ids:
            resolution = resolutions.get(identifier)
            status = getattr(resolution, "status", "missing")
            if status != "resolved":
                raise AgentCreateSkillsRefused(
                    ERR_INVALID_PARAMS,
                    f"skill does not resolve: {identifier} ({status})",
                    {
                        "reason": "skill_unresolved",
                        "skill": identifier,
                        "status": status,
                    },
                )

    def write(self, installed: list[dict[str, Any]]) -> dict[str, Any]:
        """The write, INSTANCE tier, then the ack read BACK off the row.

        Never the persona template: a persona-tier write would silently
        reconfigure every other instance of that persona, and no operator verb
        has ever done that (D5, F12/F13).
        """

        from ..persona_assignments import PersonaInstanceStore

        try:
            updated = PersonaInstanceStore().update_profile(
                self.instance_id, skills=list(self.ids), requested_by=self.requested_by
            )
        except Exception as exc:  # noqa: BLE001
            raise AgentCreateSkillsRefused(
                ERR_HANDLER_FAILED,
                f"skill assignment failed: {type(exc).__name__}: {exc}",
                {"reason": "skill_assign_failed", "skills": list(self.ids)},
            ) from exc

        return {
            # Read BACK off the row rather than echoed from the request. Gate 0
            # already guarantees the two agree; reading the store is what keeps
            # that a guarantee instead of a claim.
            "assigned": list(updated.skill_overrides or []),
            "installed": installed,
            # This phase RAN, so the instance now carries its own overrides —
            # whatever the list turned out to be, including an explicitly empty
            # one. ``inherited`` is what separates that empty list from the
            # absent request that leaves the persona's skills in force (D11):
            # both render ``assigned: []``, and a client that has only
            # ``assigned`` cannot tell "this agent was overridden with nothing"
            # from "this agent inherits everything its persona has".
            "inherited": False,
        }


def _inherited_skills_ack() -> dict[str, Any]:
    """The ``skills`` block for a create that sent no ``skills`` at all.

    ONE shape on every reply (D11): the block is present whether or not the
    phase ran, so a client never has to read an absent key as an answer. What
    the absent request means is carried by ``inherited: True`` — the new
    instance's ``skill_overrides`` stays ``None`` and it therefore inherits its
    persona's skills, LIVE, rather than being pinned to a copy of them.

    Without this flag ``assigned: []`` is two different agents wearing one
    reply: the inheriting one, and the one an operator deliberately overrode
    with ``skills: []`` (an agent with no skills at all). The launcher renders
    those differently and could not previously tell them apart.

    One window where the flag is a statement about the REQUEST rather than a
    re-read of the row: a create that crashed between ``update_profile`` and
    ``mark_done``, resumed under the same key with no ``skills``, leaves the
    overrides the crashed attempt wrote and still answers ``inherited: True``.
    Re-reading the row here would make the ack a second authority for what this
    key decided (the same argument that keeps ``persona_instance_id`` out of
    :func:`_reply`'s re-read), so the flag stays a statement of the
    request and this paragraph is the accounting for it.
    """

    return {"assigned": [], "installed": [], "inherited": True}


def _stamp_fresh_skills(result: dict[str, Any], skills_ack: dict[str, Any]) -> None:
    """Attach a skills block this call itself just BUILT.

    ``skills_fresh: True`` is not decoration here: it is trivially true —
    ``run_skills_phase`` reads ``assigned`` back off the row it has just written
    and ``installed_hash`` off the package it has just verified, microseconds
    earlier. The flag exists so a client reads ONE shape whatever answered it,
    the same rule :func:`_reply` spends on ``actor_fresh``, and it goes through
    one function so the next arm that renders a skills block cannot ship without
    it.
    """

    result["skills"] = skills_ack
    result["skills_fresh"] = True


def _observed_skills(result: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """The recorded skills block with its two OBSERVATIONS re-read — or the
    recorded block unchanged and ``False``.

    ``assigned`` is read back off ``PersonaInstance.skill_overrides``
    (``run_skills_phase`` says so in the comment beside its own return) and that
    field is mutated afterwards by ``update_profile`` — the
    ``persona instance update-profile`` verb, the launcher's skills editor.
    ``installed_hash`` names the bytes of a package the next install of the same
    id displaces. Both are observations, so a replay that echoes them is
    reporting a world that has moved, exactly as the frozen ``position`` /
    ``revision`` did before :func:`_reply` re-read the actor.

    What is deliberately NOT re-read: ``inherited``, ``installed[].skill`` and
    ``installed[].changed``. ``inherited`` is a statement about the REQUEST —
    whether a ``skills`` key was sent at all — and :func:`_inherited_skills_ack`
    already spends a paragraph on why re-deriving it from the row would make the
    ack a second authority for what this key decided. ``changed`` is what THIS
    install did, a fact about an event, not about the world now.

    ``False`` on every shape that gives nothing to look up with and on every
    read fault, and the recorded block is then returned UNCHANGED — the same
    degrade :func:`_live_actor` gets, for the same reason: a client that only
    wanted its recorded ack back is not served by a fabricated block or by a
    raise.
    """

    from ..skill_install import installed_harness_skill_hash

    recorded = dict(result.get("skills") or {})
    instance_id = result.get("persona_instance_id")
    if not instance_id:
        return recorded, False
    try:
        from ..persona_assignments import PersonaInstanceStore

        instance = PersonaInstanceStore().get(str(instance_id))
        refreshed = dict(recorded)
        refreshed["assigned"] = list(instance.skill_overrides or [])
        refreshed["installed"] = [
            {**dict(entry), "installed_hash": installed_harness_skill_hash(str(entry.get("skill") or ""))}
            for entry in (recorded.get("installed") or [])
            if isinstance(entry, dict)
        ]
    except Exception:  # noqa: BLE001 - a retired row, a decode fault, a gone root
        return recorded, False
    return refreshed, True


def _live_actor(result: dict[str, Any]) -> Any | None:
    """The actor this reply is about, read off the live store — or ``None``.

    ``None`` on every failure and on every shape that gives nothing to look up
    with: an archived actor, a deleted surface, a file that will not decode, a
    receipt written before ``workspace_id`` rode the ack. The caller renders all
    of those as ``actor_fresh: False`` rather than fabricating a row, which is
    why this never raises and never guesses a lookup key.
    """

    from ..office_store import OfficeStore

    workspace_id = result.get("workspace_id")
    actor_key = result.get("actor_key")
    if not workspace_id or not actor_key:
        return None
    try:
        return OfficeStore().get_actor(str(workspace_id), str(actor_key))
    except Exception:  # noqa: BLE001 - NotFound, a decode fault, a gone surface
        return None


def _reply(result: dict[str, Any], *, observed: Any | None = None) -> dict[str, Any]:
    """THE builder for every ``perform_agent_create`` exit that answers ``ok``.

    ``actor``, ``position``, ``revision`` and ``actor_fresh`` are stamped HERE
    and nowhere else. They used to be built independently at three sites — the
    fresh write, the ``done`` replay and the ``placed`` resume — and only one of
    them owned the rule at a time: S4 taught the ``done`` arm to re-read the
    actor, S4b (``7ecd3504d6``) taught the ``placed`` arm the same cure one
    branch over, and nothing stopped a fourth arm from freezing it again. One
    builder is the structural answer; the arms now differ only in WHAT they
    observed, which is the one thing that actually differs between them.

    ``observed`` is the actor row this call itself WROTE. Omitted, the exit
    wrote no row of its own and the live one is read here
    (:func:`_live_actor`) — which is what makes a replay adopt the row as it is
    NOW rather than as it was when the key first completed.

    Why the re-read exists at all: a ``done``/``placed`` receipt records the ack
    the FIRST attempt returned, and the office actor has been mutable ever
    since — an operator drags the agent, a realm pull moves it,
    ``resolve_conflict`` bumps it. Returning the recorded
    ``position``/``actor``/``revision`` verbatim therefore hands a replaying
    client the coordinates the agent had at 09:00 and calls them current.

    That was harmless while ``actor`` was decoration. It stops being harmless in
    plan S7, where the launcher ADOPTS the ack's actor — key, position and
    revision — into its scene and its ``expect_revision`` bookkeeping. A stale
    ``revision`` adopted from a replay makes the client's very next guarded
    write refuse ``stale_revision``, and a stale ``position`` snaps the agent
    back to where it used to be. So the re-read happens here, hermes-side,
    BEFORE that adoption exists rather than after it has been debugged.

    What is deliberately NOT stamped here: ``persona_instance_id``,
    ``placement_id``, ``default_chat_session_id`` and ``actor_key``. Those are
    IDENTITY and the recorded decision, not observations — re-deriving them
    would be a second authority for what this key created, and ``actor_key`` in
    particular is the key the observation was made WITH.

    ``skills`` used to be on that list and it did not belong there (2026-09-02).
    The BLOCK is a mix: ``inherited`` is the recorded decision and stays
    verbatim, but ``assigned`` mirrors ``PersonaInstance.skill_overrides``,
    which ``update_profile`` mutates, and ``installed[].installed_hash`` names
    bytes the next install of the same id displaces. Both are observations, so
    both are re-read here (:func:`_observed_skills`) under a ``skills_fresh``
    valve shaped exactly like ``actor_fresh``.

    **The "no second write happened" witness moves.** It used to be the ack's
    ``revision``, which is exactly the field this function stops freezing. The
    witness is now the RECEIPT FILE: state ``done`` is written once and a replay
    does not touch it, so a test that wants to prove nothing was written asserts
    on the receipt (and on the actor's own revision read from the store), never
    on the reply.

    ``actor_fresh`` is the honesty valve, and it is ONE shape on every reply:
    present whether the row was written by this call (trivially ``true``) or
    read for it. When a read finds nothing — the actor was archived, the
    workspace was deleted, the file will not decode — the recorded row is
    returned UNCHANGED and the flag says so. It is never fabricated and never
    omitted: a client that must know whether it may adopt gets an answer on
    every reply rather than having to infer one from a missing key.
    """

    from ..office_models import office_actor_wire_row

    result = dict(result)
    if "skills" in result:
        # Only a REPLAY arrives carrying one: the fresh and ``placed`` arms
        # attach theirs after this builder runs, through
        # :func:`_stamp_fresh_skills`. So this is the recorded block, and its two
        # observations are re-read for the same reason the actor's are.
        result["skills"], result["skills_fresh"] = _observed_skills(result)
    actor = observed if observed is not None else _live_actor(result)
    if actor is None:
        result["actor_fresh"] = False
        return result
    # The AGENT item's position, because that is what the ack's ``position``
    # names: this verb writes exactly one item and it is of kind ``agent``
    # (D6 — it authors no desk). The fallback to "the first item that has a
    # position" is for a row something else has since added an item to, where
    # answering ``None`` would be worse than answering the row's own first
    # coordinate.
    items = list(getattr(actor, "items", ()) or ())
    position = None
    for candidate in (
        [item for item in items if getattr(item, "kind", None) == "agent"] + items
    ):
        raw = getattr(candidate, "position", None)
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            position = [float(raw[0]), float(raw[1])]
            break
    result["actor"] = office_actor_wire_row(actor)
    result["revision"] = actor.revision
    if position is not None:
        # Only when the row actually carries one. An actor whose items lost
        # their coordinates is a store fault, and echoing the recorded position
        # beside a freshly-read actor would be the half-fresh reply that is
        # worse than either honest answer.
        result["position"] = position
    result["actor_fresh"] = True
    return result


def compensate_failed_placement(
    reservation, *, instance_id: str, failure: dict[str, Any]
) -> dict[str, Any]:
    """Compensate a failed placement and return the ``data`` block for the reply.

    Order matters and is the same order the whole sequence uses: undo the write
    that DID land before answering, so the caller's failure and the store agree.
    ``rolled_back`` is the field a client branches on and it is never optimistic
    — a compensation that raised reports ``false`` and names the instance that
    survived, because the alternative (claiming a rollback that did not happen)
    is the half-state this sequence exists to abolish, now with a lie on top.
    """

    from ..persona_assignments import PersonaInstanceStore

    try:
        PersonaInstanceStore().retire(
            instance_id,
            reason="runtime.agent.create placement failed",
            requested_by="runtime.agent.create",
        )
    except Exception as exc:  # noqa: BLE001 - every retire refusal lands here
        reservation.mark_rollback_failed(
            failure, rollback_error=f"{type(exc).__name__}: {exc}"
        )
        return {
            **failure,
            "rolled_back": False,
            "persona_instance_id": instance_id,
            "rollback_error": f"{type(exc).__name__}: {exc}",
        }
    reservation.mark_rolled_back(failure)
    return {**failure, "rolled_back": True}
