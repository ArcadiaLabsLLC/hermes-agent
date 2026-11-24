"""Every frame on a call names its receiver, and the receiver checks it machine first.

Row ``RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST`` (owner
2026-11-23: "starting with machine id"; 2026-11-24: "2 keep it all , its a consistent standard like how
ip addresses and ports work"). After the call's hello, every frame either side writes is::

    {"lane": "<32 hex>", "to": "machine:<id>/namespace:<id>", "install": "<install id>", ...}

``to`` is the receiver's address in ``agent_runtime.address``'s grammar and order; ``install`` is the
receiver's install id. The receiver reads them in that order — the machine segment, then the namespace
segment, then the install id — and a mismatch at any step drops the frame there: nothing after it is
read, the namespace included when the machine is wrong (:func:`address_refusal`). The typed word goes on
the serve's own log as ``pair_call_address_mismatch`` with ids only; nothing is answered on the wire.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any, Final, Mapping

__layer__ = "models"

__all__ = [
    "ID_PATTERN",
    "MISMATCH_INSTALL",
    "MISMATCH_MACHINE",
    "MISMATCH_NAMESPACE",
    "Endpoint",
    "address_refusal",
    "mint_id",
    "wrap",
]

#: A call id or a lane id: 32 lowercase hex characters, minted by the side that opens it.
ID_PATTERN: Final = re.compile(r"^[0-9a-f]{32}$")

MISMATCH_MACHINE: Final = "pair_call_machine_mismatch"
MISMATCH_NAMESPACE: Final = "pair_call_namespace_mismatch"
MISMATCH_INSTALL: Final = "pair_call_install_mismatch"


def mint_id() -> str:
    return secrets.token_hex(16)


@dataclass(frozen=True, slots=True)
class Endpoint:
    """One side of a call: the machine, namespace and install a frame to it must name."""

    machine_id: str
    namespace: str
    install_id: str

    def to(self) -> str:
        return f"machine:{self.machine_id}/namespace:{self.namespace}"

    def describe(self) -> dict[str, str]:
        return {"machine_id": self.machine_id, "namespace": self.namespace, "install_id": self.install_id}


def wrap(lane: str, receiver: Endpoint, body: Mapping[str, Any]) -> dict[str, Any]:
    """*body* addressed to *receiver* on *lane*: the three address keys lead every frame."""

    return {"lane": lane, "to": receiver.to(), "install": receiver.install_id, **body}


def address_refusal(frame: Mapping[str, Any], own: Endpoint) -> str | None:
    """Why *frame* is not for *own*, in address order; ``None`` lets the receiver read the rest.

    The machine segment is read and compared before the namespace segment is looked at, and the
    install id only after both: a frame for another machine is dropped on its first segment.
    """

    to = frame.get("to")
    if not isinstance(to, str):
        return MISMATCH_MACHINE
    first, _, rest = to.partition("/")
    # MUTATION: compare the namespace segment (``rest``) before this one and
    # test_pair_call's test_a_frame_for_another_machine_is_dropped_before_its_namespace_is_read logs
    # the namespace word for a frame wrong on both.
    if first != f"machine:{own.machine_id}":
        return MISMATCH_MACHINE
    if rest != f"namespace:{own.namespace}":
        return MISMATCH_NAMESPACE
    if frame.get("install") != own.install_id:
        return MISMATCH_INSTALL
    return None
