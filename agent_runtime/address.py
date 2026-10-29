"""The one typed address: every segment carries its kind, so no bare id names anything (row ``RT-NAMING-ADDRESS-VALUE``).

Plan ``docs/agent-runtime-harness/planned/naming-and-address-map-2026-10-25.md`` § The address::

    machine:<machine-id>/namespace:<id>/persona-instance:<id>/chat:<id>/turn:<id>
    project:<id>/repo-slot:<name>                                          (shared, synced)
    machine:<machine-id>/namespace:<id>/slot-folder:<project>/<slot>       (the join)
    realm:<id>/realm-workspace:<id>/repo-slot:<name>                       (read, never printed again)

A repo slot is declared by a Project and named ``<project>/<slot>`` (plan
``project-slots-and-shared-chats-2026-10-29.md`` §3, §8): ``slot-folder``'s pair is ``<project>/<slot>``
(a workspace-document slot not yet migrated still prints its workspace id there), and the
``realm:/realm-workspace:/repo-slot:`` chain stays parseable for old turn records.

:class:`Address` is the value; ``str(address)`` prints it and :func:`parse` reads it back, the one format
both ways. An address is any non-empty PREFIX of one of the four chains above (``machine:…/namespace:…``
is an address; ``chat:…`` alone is not). ``namespace:base`` names the base root (``BASE_ID``), which is
not a namespace but is where a process with no ``HERMES_NAMESPACE`` keeps its data. Editions are never a
segment (ruling 9): the edition that ran a turn is a stamp beside the address (``ran_by``).

The launcher holds the same value (``MC-ADDRESS-VALUE-LAUNCHER``); the grammar here is the contract.
Every turn record prints it (:func:`turn_address`); the audit read (``RT-TURN-AUDIT-ENTRY``) and the agent
commit trailer (``RT-AGENT-COMMIT-ATTRIBUTION``) print the same string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__layer__ = "stores"


class Kind(StrEnum):
    MACHINE = "machine"
    NAMESPACE = "namespace"
    PERSONA_INSTANCE = "persona-instance"
    CHAT = "chat"
    TURN = "turn"
    REALM = "realm"
    REALM_WORKSPACE = "realm-workspace"
    REPO_SLOT = "repo-slot"
    SLOT_FOLDER = "slot-folder"
    PROJECT = "project"


#: The four chains, in order. An address is a non-empty prefix of one of them.
CHAINS: tuple[tuple[Kind, ...], ...] = (
    (Kind.MACHINE, Kind.NAMESPACE, Kind.PERSONA_INSTANCE, Kind.CHAT, Kind.TURN),
    (Kind.PROJECT, Kind.REPO_SLOT),
    (Kind.REALM, Kind.REALM_WORKSPACE, Kind.REPO_SLOT),
    (Kind.MACHINE, Kind.NAMESPACE, Kind.SLOT_FOLDER),
)

#: One id: no ``/`` (the segment separator), no whitespace, no control character; ``:`` is allowed
#: inside an id because only the FIRST ``:`` of a segment splits kind from id.
_ID = re.compile(r"[^/\s\x00-\x1f\x7f]{1,240}")


class AddressError(ValueError):
    """Text that is not an address, or segments that form no chain."""


@dataclass(frozen=True, slots=True)
class Segment:
    kind: Kind
    #: For ``slot-folder`` this is ``<project>/<slot>`` — the one segment whose id is a pair.
    id: str

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.id}"


def _check_id(kind: Kind, value: str) -> str:
    parts = value.split("/") if kind is Kind.SLOT_FOLDER else [value]
    if (kind is Kind.SLOT_FOLDER and len(parts) != 2) or not all(_ID.fullmatch(part) for part in parts):
        want = "<project>/<slot>" if kind is Kind.SLOT_FOLDER else "an id with no '/' or whitespace"
        raise AddressError(f"{kind.value}: {value!r} is not {want}")
    return value


@dataclass(frozen=True, slots=True)
class Address:
    segments: tuple[Segment, ...]

    def __post_init__(self) -> None:
        kinds = tuple(segment.kind for segment in self.segments)
        if not kinds or not any(chain[: len(kinds)] == kinds for chain in CHAINS):
            raise AddressError(f"{'/'.join(k.value for k in kinds) or '(empty)'} is a prefix of no address chain")
        for segment in self.segments:
            _check_id(segment.kind, segment.id)

    @classmethod
    def of(cls, *pairs: tuple[Kind | str, str]) -> Address:
        return cls(tuple(Segment(Kind(kind), str(value)) for kind, value in pairs))

    def child(self, kind: Kind | str, value: str) -> Address:
        return Address((*self.segments, Segment(Kind(kind), str(value))))

    def get(self, kind: Kind | str) -> str | None:
        wanted = Kind(kind)
        return next((segment.id for segment in self.segments if segment.kind is wanted), None)

    def __str__(self) -> str:
        return "/".join(str(segment) for segment in self.segments)


def parse(text: str) -> Address:
    """The address *text* prints, or :class:`AddressError`. ``parse(str(a)) == a`` for every address."""

    raw = str(text or "")
    segments: list[Segment] = []
    tokens = raw.split("/") if raw else []
    i = 0
    while i < len(tokens):
        kind_text, sep, value = tokens[i].partition(":")
        try:
            kind = Kind(kind_text)
        except ValueError:
            raise AddressError(f"{tokens[i]!r} does not open with a known kind") from None
        if not sep:
            raise AddressError(f"{tokens[i]!r} has no ':' — a bare kind names nothing")
        if kind is Kind.SLOT_FOLDER:
            if i + 1 >= len(tokens):
                raise AddressError("slot-folder needs <project>/<slot>")
            value, i = f"{value}/{tokens[i + 1]}", i + 1
        segments.append(Segment(kind, value))
        i += 1
    return Address(tuple(segments))


def here() -> Address | None:
    """``machine:<id>/namespace:<id>`` for this process, minting the machine id once; ``None`` when unavailable."""

    from hermes_cli._namespace_bootstrap import BASE_ID, namespace_stamp

    from .machine_identity import MachineIdentityUnavailable, ensure_machine_id

    try:
        machine = ensure_machine_id()
    except MachineIdentityUnavailable:
        return None
    try:
        return Address.of((Kind.MACHINE, machine), (Kind.NAMESPACE, namespace_stamp() or BASE_ID))
    except AddressError:
        return None


def turn_address(*, persona_instance_id: str | None, chat_id: str | None, turn_id: str | None) -> Address | None:
    """The full turn address, or ``None`` when any segment is unknown or malformed (absent stays absent)."""

    root = here()
    if root is None or not (persona_instance_id and chat_id and turn_id):
        return None
    try:
        return root.child(Kind.PERSONA_INSTANCE, persona_instance_id).child(Kind.CHAT, chat_id).child(Kind.TURN, turn_id)
    except AddressError:
        return None
