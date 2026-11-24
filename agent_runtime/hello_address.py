"""Which machine and namespace a hello comes from, and which a ``hello_ok`` answers from.

Row ``RT-ACCOUNT-ONLY-A-CONNECTION-FROM-ANOTHER-MACHINE-THAN-THE-ONE-YOUR-DEVICE-PAIRED-WITH-IS-DROPPED-FIRST``
(owner 2026-11-23: "there are namespaces so it should use the namespaces to confirm the connection is going
to the right device" / "right it should be both" / "starting with machine id"). A connection between two of
your devices is checked against the other side's address in ADDRESS ORDER (``agent_runtime.address``):
the machine id first, then the namespace, and only then the install and the proof.

* **The server side** (:func:`hello_address_refusal`): every credential row that proves a caller — a
  device row, a peer row, a phone's grant — stores the OTHER side's machine id, bound at an account-checked
  pairing. A hello names ``machine_id`` (its process's own, :func:`hello_fields`) and ``namespace`` (its
  stamp). The named machine id is compared with the row's (absent on either side, or different: refused),
  then the namespace with this process's own. A mismatch stops there: nothing past it runs, the proof
  included. Each refusal is the lane's ONE collapsed wire reason; the typed local word
  (:data:`HELLO_MACHINE_MISMATCH` / :data:`HELLO_NAMESPACE_MISMATCH`) rides only the serve's own log.
* **The client side** (:func:`answer_address_refusal`): ``hello_ok``'s ``install`` block names the serve's
  ``machine_id`` and ``namespace`` (:func:`install_address`); every hermes dialer checks them, in the same
  order, against the machine id its caller handed it and its own namespace, after the pin and before it
  sends a request.

No legacy (owner 2026-11-23: "don't develop for legacy stuff"): a row minted before this has no machine id
and is refused; the device re-pairs through the account. The machine id's one owner stays
``agent_runtime.machine_identity``; this module only reads it and checks shapes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

__layer__ = "stores"

__all__ = [
    "HELLO_MACHINE_ID",
    "HELLO_MACHINE_MISMATCH",
    "HELLO_NAMESPACE",
    "HELLO_NAMESPACE_MISMATCH",
    "answer_address_refusal",
    "clean_machine_id",
    "hello_address_refusal",
    "hello_fields",
    "install_address",
    "own_namespace",
]

#: The two hello (and ``hello_ok.install``) keys this module owns.
HELLO_MACHINE_ID: Final = "machine_id"
HELLO_NAMESPACE: Final = "namespace"
#: The typed local reasons. Never on the wire: the lane's collapsed reason is.
HELLO_MACHINE_MISMATCH: Final = "hello_machine_mismatch"
HELLO_NAMESPACE_MISMATCH: Final = "hello_namespace_mismatch"

_ID_LIMIT = 128


def clean_machine_id(value: Any) -> str | None:
    """*value* when it has hermes' own mint shape (``machine_identity.MACHINE_ID_PREFIX``), else ``None``."""

    from .machine_identity import MACHINE_ID_PREFIX

    text = value.strip() if isinstance(value, str) else ""
    if not text.startswith(MACHINE_ID_PREFIX) or len(text) <= len(MACHINE_ID_PREFIX) or len(text) > _ID_LIMIT:
        return None
    if not all(ch.isalnum() or ch in "_-" for ch in text):
        return None
    return text


def own_namespace() -> str:
    """This process's namespace id: its stamp, or ``base`` for the base root (the address's spelling)."""

    from hermes_cli._namespace_bootstrap import BASE_ID, namespace_stamp

    return namespace_stamp() or BASE_ID


def _own_machine_id() -> str | None:
    from .machine_identity import MachineIdentityUnavailable, ensure_machine_id

    try:
        return clean_machine_id(ensure_machine_id())
    except MachineIdentityUnavailable:
        return None


def hello_fields() -> dict[str, str]:
    """The two fields every hermes client hello names: this process's machine id and namespace.

    Empty of ``machine_id`` when this process cannot read or mint one; the far side then refuses the
    hello, which is the honest answer for a client that cannot say where it runs.
    """

    machine = _own_machine_id()
    return {**({HELLO_MACHINE_ID: machine} if machine else {}), HELLO_NAMESPACE: own_namespace()}


def install_address() -> dict[str, Any]:
    """``hello_ok.install``'s two address keys: the serve's machine id (``None`` when unavailable) and namespace."""

    return {HELLO_MACHINE_ID: _own_machine_id(), HELLO_NAMESPACE: own_namespace()}


def hello_address_refusal(message: Mapping[str, Any], *, row_machine_id: Any) -> str | None:
    """The server's first two checks, in address order. ``None`` admits to the next step.

    1. the machine id the hello names against the credential row's: absent on either side, or
       different, is :data:`HELLO_MACHINE_MISMATCH`;
    2. the namespace the hello names against this process's own: :data:`HELLO_NAMESPACE_MISMATCH`.
    """

    named = clean_machine_id(message.get(HELLO_MACHINE_ID))
    bound = clean_machine_id(row_machine_id)
    # MUTATION: read an absent row machine id as a match (`bound is not None and`) and
    # test_a_row_with_no_machine_id_is_refused admits a credential minted before the binding.
    if named is None or bound is None or named != bound:
        return HELLO_MACHINE_MISMATCH
    if message.get(HELLO_NAMESPACE) != own_namespace():
        return HELLO_NAMESPACE_MISMATCH
    return None


def answer_address_refusal(answer: Any, *, expect_machine_id: Any) -> str | None:
    """A dialer's check of the ``hello_ok`` it read, machine first. ``None`` lets it send a request.

    *expect_machine_id* is what the dialer's caller handed it (the far device's machine id from the
    account, a grant's or a peer row's); the namespace must be this process's own.
    """

    install = answer.get("install") if isinstance(answer, Mapping) else None
    install = install if isinstance(install, Mapping) else {}
    named = clean_machine_id(install.get(HELLO_MACHINE_ID))
    expected = clean_machine_id(expect_machine_id)
    if named is None or expected is None or named != expected:
        return HELLO_MACHINE_MISMATCH
    if install.get(HELLO_NAMESPACE) != own_namespace():
        return HELLO_NAMESPACE_MISMATCH
    return None
