"""The phone's grants: which paired computer may drive this phone's engine, and how much.

``<store_root>/gateway/reverse_grants.json``, one row per granted computer. A row holds
the grant LEVEL (``look`` | ``chat``, each an allowlist in ``call_authorization``, never a
device tier; or ``account``, which the phone's own Eternia grants only to a computer it proved is
on the phone's account, answered by ``call_authorization.paired_device_answers``), the computer's id on this phone, the VERIFIER of the credential the phone
minted for it (``sha256(token)``; the token itself leaves once, to the computer, and is
never stored here), and the pairing it is bound to: the computer's install id and the
device id this phone holds on that computer. A dial under a different pairing finds no
grant, so a re-pair starts with none (review w1118a.79).

The grant row ``MC-PHONE-DRIVEN-A-PHONE-LETS-A-PAIRED-COMPUTER-USE-ITS-AGENTS`` builds the
offer, the accept and the switch on top of :func:`grant_computer` and :func:`revoke_grant`.
"""

from __future__ import annotations

import hmac
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..call_authorization import COMPUTER_GRANT_ACCOUNT, COMPUTER_GRANT_CHAT, COMPUTER_GRANT_LOOK, COMPUTER_GRANTS
from ..clock import now_iso
from ..paths import gateway_dir
from ..serve_gateway_auth.proof import device_verifier, reverse_proof_from_verifier
from ..store_file_io import read_json_object as _read_json
from ..store_file_io import store_lock as _file_lock
from ..store_file_io import write_secure_json as _write_secure

__layer__ = "stores"

__all__ = [
    "GRANT_ACCOUNT",
    "GRANT_CHAT",
    "GRANT_LEVELS",
    "GRANT_LOOK",
    "REVERSE_GRANTS_FILENAME",
    "ReverseGrant",
    "ReverseGrantCredential",
    "add_level_listener",
    "add_revoke_listener",
    "change_level",
    "grant_computer",
    "grant_for_install",
    "list_grants",
    "revoke_grant",
    "revoke_install_grants",
    "verify_lane_proof",
]

#: Look: the phone's agents, their chats and history, read only.
GRANT_LOOK = COMPUTER_GRANT_LOOK
#: Look, and run chat turns on the phone's agents.
GRANT_CHAT = COMPUTER_GRANT_CHAT
#: A computer on the phone's own account: everything a console-tier paired device is answered.
GRANT_ACCOUNT = COMPUTER_GRANT_ACCOUNT
GRANT_LEVELS: tuple[str, ...] = COMPUTER_GRANTS

REVERSE_GRANTS_FILENAME = "reverse_grants.json"
_CONTRACT = 1
_ID_LIMIT = 128


@dataclass(frozen=True, slots=True)
class ReverseGrant:
    """One granted computer, as this phone holds it. No secret: the verifier has no field."""

    computer_id: str
    level: str
    computer_install_id: str
    pairing_device_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ReverseGrantCredential:
    """What :func:`grant_computer` hands back ONCE: the computer's id and its token."""

    computer_id: str
    token: str
    level: str

    def __repr__(self) -> str:  # the token never reaches a log through a repr
        return f"ReverseGrantCredential(computer_id={self.computer_id!r}, level={self.level!r})"


_listeners: list[Callable[[list[str]], None]] = []
_listeners_lock = threading.Lock()


def add_revoke_listener(listener: Callable[[list[str]], None]) -> Callable[[], None]:
    """Be told the computer ids whose grants were just deleted; returns the remover.

    The serve's reverse lanes listen, so a grant turned off closes its open lane at once.
    """

    with _listeners_lock:
        _listeners.append(listener)

    def remove() -> None:
        with _listeners_lock:
            if listener in _listeners:
                _listeners.remove(listener)

    return remove


_level_listeners: list[Callable[[list[str]], None]] = []


def add_level_listener(listener: Callable[[list[str]], None]) -> Callable[[], None]:
    """Be told the computer ids whose grant LEVEL just changed in place; returns the remover.

    The serve's reverse lanes listen and close those computers' live lanes, so a redial's hello
    is stamped at the new level (the level is stamped on a connection at its hello). The dialer
    is left running: the credential still verifies.
    """

    with _listeners_lock:
        _level_listeners.append(listener)

    def remove() -> None:
        with _listeners_lock:
            if listener in _level_listeners:
                _level_listeners.remove(listener)

    return remove


def _notify_level(changed: list[str]) -> None:
    if not changed:
        return
    with _listeners_lock:
        listeners = list(_level_listeners)
    for listener in listeners:
        try:
            listener(list(changed))
        except Exception:
            pass


def _notify(revoked: list[str]) -> None:
    if not revoked:
        return
    with _listeners_lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(list(revoked))
        except Exception:
            pass


def _path(store_root: Path | str) -> Path:
    return gateway_dir(store_root) / REVERSE_GRANTS_FILENAME


def _lock(store_root: Path | str):
    return _file_lock(gateway_dir(store_root) / "reverse_grants.lock")


def _rows(store_root: Path | str) -> dict[str, dict[str, Any]]:
    payload = _read_json(_path(store_root))
    rows = payload.get("grants") if isinstance(payload, dict) else None
    return {str(k): v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}


def _write(store_root: Path | str, rows: dict[str, dict[str, Any]]) -> None:
    path = _path(store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_secure(path, {"contract": _CONTRACT, "grants": rows})


def _grant_row(computer_id: str, row: dict[str, Any]) -> ReverseGrant | None:
    level = row.get("level")
    install = str(row.get("computer_install_id") or "").strip()
    pairing = str(row.get("pairing_device_id") or "").strip()
    if level not in GRANT_LEVELS or not install or not pairing or not row.get("verifier"):
        return None
    return ReverseGrant(computer_id=computer_id, level=str(level), computer_install_id=install,
                        pairing_device_id=pairing, created_at=str(row.get("created_at") or ""))


def _grant_id_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > _ID_LIMIT or not text.isprintable() or "|" in text:
        raise ValueError(f"not a usable id: {text!r}")
    return text


def grant_computer(store_root: Path | str, *, computer_install_id: str, pairing_device_id: str,
                   level: str = GRANT_LOOK) -> ReverseGrantCredential:
    """Grant the computer this phone is paired with as ``pairing_device_id``; mint its credential.

    One grant per computer install: a new grant replaces the old one, whose credential stops
    verifying at once. Read by default.
    """

    if level not in GRANT_LEVELS:
        raise ValueError(f"grant level must be one of {GRANT_LEVELS}, not {level!r}")
    install = _grant_id_text(computer_install_id)
    pairing = _grant_id_text(pairing_device_id)
    computer_id = f"cmp-{secrets.token_hex(8)}"
    token = secrets.token_hex(32)
    with _lock(store_root):
        rows = _rows(store_root)
        replaced = [cid for cid, row in rows.items() if row.get("computer_install_id") == install]
        for cid in replaced:
            rows.pop(cid, None)
        rows[computer_id] = {"level": level, "computer_install_id": install, "pairing_device_id": pairing,
                             "verifier": device_verifier(token), "created_at": now_iso()}
        _write(store_root, rows)
    _notify(replaced)
    return ReverseGrantCredential(computer_id=computer_id, token=token, level=level)


def change_level(store_root: Path | str, *, computer_install_id: str, pairing_device_id: str,
                 level: str) -> ReverseGrant | None:
    """Change the level of the grant this computer install already holds on this pairing, in place.

    Hermes row RT-FU-A-PHONE-CHANGING-A-COMPUTERS-LEVEL-KEEPS-ITS-CREDENTIAL-AND-ITS-ACCEPT (review
    w1122b.5): the same ``computer_id`` and verifier, so the credential the computer accepted keeps
    verifying and no second Accept is asked; the level listeners close its live lane before this
    returns, so a downgrade binds on its next call. ``None`` when there is no such grant (none, or one
    under another pairing): the caller grants afresh and offers, a first consent.
    """

    if level not in GRANT_LEVELS:
        raise ValueError(f"grant level must be one of {GRANT_LEVELS}, not {level!r}")
    install = _grant_id_text(computer_install_id)
    pairing = _grant_id_text(pairing_device_id)
    with _lock(store_root):
        rows = _rows(store_root)
        held = [(cid, row) for cid, row in rows.items()
                if row.get("computer_install_id") == install and row.get("pairing_device_id") == pairing
                and _grant_row(cid, row) is not None]
        if len(held) != 1:
            return None
        computer_id, row = held[0]
        changed = row.get("level") != level
        row["level"] = level
        if changed:
            _write(store_root, rows)
    if changed:
        # MUTATION: skip this notice and test_reverse_lane's downgrade test keeps a live lane stamped chat.
        _notify_level([computer_id])
    return _grant_row(computer_id, row)


def revoke_grant(store_root: Path | str, computer_id: str) -> bool:
    """Delete one grant. Its lanes close (the listeners). True when there was one."""

    computer_id = str(computer_id or "").strip()
    with _lock(store_root):
        rows = _rows(store_root)
        existed = rows.pop(computer_id, None) is not None
        if existed:
            _write(store_root, rows)
    if existed:
        _notify([computer_id])
    return existed


def revoke_install_grants(store_root: Path | str, computer_install_id: str) -> list[str]:
    """Delete every grant for one computer install (it unpaired us). Returns the ids."""

    install = str(computer_install_id or "").strip()
    with _lock(store_root):
        rows = _rows(store_root)
        gone = [cid for cid, row in rows.items() if row.get("computer_install_id") == install]
        for cid in gone:
            rows.pop(cid, None)
        if gone:
            _write(store_root, rows)
    _notify(gone)
    return gone


def list_grants(store_root: Path | str) -> list[ReverseGrant]:
    grants = (_grant_row(cid, row) for cid, row in _rows(store_root).items())
    return sorted((g for g in grants if g is not None), key=lambda g: g.computer_id)


def grant_for_install(store_root: Path | str, computer_install_id: str) -> ReverseGrant | None:
    install = str(computer_install_id or "").strip()
    return next((g for g in list_grants(store_root) if g.computer_install_id == install), None)


def verify_lane_proof(store_root: Path | str, computer_id: Any, presented: Any, nonce: str, *,
                      lane_id: str) -> ReverseGrant | None:
    """Constant-time check of a granted computer's hello over a lane. ``None`` refuses.

    Fails closed on every missing input, like ``serve_gateway_auth.verify_device_proof``.
    """

    computer_id = str(computer_id or "").strip()
    if not computer_id or len(computer_id) > _ID_LIMIT or not nonce or not lane_id:
        return None
    if not isinstance(presented, str) or not presented.strip():
        return None
    row = _rows(store_root).get(computer_id)
    grant = _grant_row(computer_id, row) if isinstance(row, dict) else None
    if grant is None:
        return None
    expected = reverse_proof_from_verifier(str(row["verifier"]), nonce, lane_id=lane_id, device_id=computer_id)
    if not hmac.compare_digest(presented.strip().lower().encode("utf-8", "replace"), expected.encode("ascii")):
        return None
    return grant
