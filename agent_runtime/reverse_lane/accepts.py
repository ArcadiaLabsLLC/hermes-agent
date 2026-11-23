"""The computer's side of a phone's grant: the offers it holds and the ones its owner accepted.

Row ``MC-PHONE-DRIVEN-A-PHONE-LETS-A-PAIRED-COMPUTER-USE-ITS-AGENTS`` (Eternia), plan
``PHONE_DRIVEN_BY_A_COMPUTER_2026-11-21`` §4 "the reverse grant" and §15. One consent, the
phone's; a computer on the phone's own account needs no Accept press (owner 2026-11-23: "No, drop
Accept"):

1. The phone's operator turns this computer on, on the phone. The phone's engine mints the
   computer's credential and OFFERS it here once, over its own pinned TLS connection, as a
   paired device (``runtime.gateway.reverse.offer``). An offer is held in MEMORY only, keyed
   by the device that sent it — a token at rest on this disk would be a second copy of the
   phone's secret — and it ends with this serve. The phone offers again when it must.
2. This computer's Eternia takes the offer by itself, with no press, because the phone is on
   its own account (``runtime.gateway.reverse.accept``, still local console only; Eternia row
   ``MC-ACCOUNT-ONLY-YOUR-COMPUTER-USES-YOUR-PHONES-AGENTS-WITHOUT-PRESSING-ACCEPT``). The token
   leaves here once, to Eternia, which keeps it in its install credential store; this module
   writes down only the non-secret fact that the phone's device on this computer granted it:
   ``<store_root>/gateway/reverse_accepts.json``. A stored accept still holding the retired
   ``look`` or ``chat`` level is dropped on the next read, with no store migration.

The accept is bound to the pairing like the grant: a row whose device is no longer paired
here (revoked, expired, gone) is not answered and is dropped on the next read, so a re-pair
starts with none (review w1118a.79).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..clock import now_iso
from ..paths import gateway_dir
from ..store_file_io import read_json_object as _read_json
from ..store_file_io import store_lock as _file_lock
from ..store_file_io import write_secure_json as _write_secure
from .grants import GRANT_LEVELS

__layer__ = "stores"

__all__ = [
    "OFFER_TTL_SECONDS",
    "REVERSE_ACCEPTS_FILENAME",
    "ReverseAccept",
    "ReverseOffer",
    "ReverseOffers",
    "forget_accept",
    "list_accepts",
    "record_accept",
]

REVERSE_ACCEPTS_FILENAME = "reverse_accepts.json"
_CONTRACT = 1
#: How long an offer waits for this computer's operator before it lapses.
OFFER_TTL_SECONDS = 15 * 60
_ID_LIMIT = 128


@dataclass(frozen=True, slots=True)
class ReverseOffer:
    """One phone's pending offer. The token is held, and never rendered."""

    device_id: str
    computer_id: str
    level: str
    phone_install_id: str
    token: str
    offered_at: float

    def describe(self) -> dict[str, Any]:
        """The offer as a surface shows it: everything but the token."""

        return {"device_id": self.device_id, "computer_id": self.computer_id, "level": self.level,
                "phone_install_id": self.phone_install_id, "offered_at": self.offered_at}

    def __repr__(self) -> str:  # the token never reaches a log through a repr
        return f"ReverseOffer(device_id={self.device_id!r}, level={self.level!r})"


@dataclass(frozen=True, slots=True)
class ReverseAccept:
    """One phone this computer's owner accepted. No secret: the token is Eternia's."""

    device_id: str
    computer_id: str
    level: str
    phone_install_id: str
    accepted_at: str

    def describe(self) -> dict[str, Any]:
        """The accept as a surface shows it."""

        return {"device_id": self.device_id, "computer_id": self.computer_id, "level": self.level,
                "phone_install_id": self.phone_install_id, "accepted_at": self.accepted_at}


def _id_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > _ID_LIMIT or not text.isprintable() or "|" in text:
        return None
    return text


class ReverseOffers:
    """The offers one serve holds, in memory: one per paired device, the newest wins."""

    def __init__(self, *, clock: Any = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._offers: dict[str, ReverseOffer] = {}

    def hold(self, *, device_id: str, computer_id: Any, level: Any, phone_install_id: Any,
             token: Any) -> ReverseOffer | None:
        """Hold *device_id*'s offer. ``None`` when a field is not one an offer can carry."""

        computer = _id_text(computer_id)
        install = _id_text(phone_install_id)
        secret = token.strip() if isinstance(token, str) else ""
        if computer is None or install is None or level not in GRANT_LEVELS:
            return None
        if not 32 <= len(secret) <= 256 or not secret.isalnum():
            return None
        offer = ReverseOffer(device_id=str(device_id), computer_id=computer, level=str(level),
                             phone_install_id=install, token=secret, offered_at=self._clock())
        with self._lock:
            self._offers[offer.device_id] = offer
        return offer

    def take(self, device_id: str) -> ReverseOffer | None:
        """Remove and answer *device_id*'s live offer (the accept), or ``None``."""

        with self._lock:
            offer = self._offers.pop(str(device_id or ""), None)
        if offer is None or self._clock() - offer.offered_at > OFFER_TTL_SECONDS:
            return None
        return offer

    def drop(self, device_id: str) -> bool:
        with self._lock:
            return self._offers.pop(str(device_id or ""), None) is not None

    def pending(self) -> list[ReverseOffer]:
        now = self._clock()
        with self._lock:
            for key in [k for k, o in self._offers.items() if now - o.offered_at > OFFER_TTL_SECONDS]:
                self._offers.pop(key, None)
            return sorted(self._offers.values(), key=lambda o: o.device_id)

    def clear(self) -> None:
        with self._lock:
            self._offers.clear()


def _path(store_root: Path | str) -> Path:
    return gateway_dir(store_root) / REVERSE_ACCEPTS_FILENAME


def _lock(store_root: Path | str):
    return _file_lock(gateway_dir(store_root) / "reverse_accepts.lock")


def _rows(store_root: Path | str) -> dict[str, dict[str, Any]]:
    payload = _read_json(_path(store_root))
    rows = payload.get("accepts") if isinstance(payload, dict) else None
    return {str(k): v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}


def _write(store_root: Path | str, rows: dict[str, dict[str, Any]]) -> None:
    path = _path(store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_secure(path, {"contract": _CONTRACT, "accepts": rows})


def _paired_here(store_root: Path | str, device_id: str) -> bool:
    from ..serve_gateway_auth import lookup_device

    record = lookup_device(store_root, device_id)
    return record is not None and not record.revoked and not record.expired


def record_accept(store_root: Path | str, offer: ReverseOffer) -> ReverseAccept:
    """Write down that this computer's owner accepted *offer*. One row per phone device."""

    accept = ReverseAccept(device_id=offer.device_id, computer_id=offer.computer_id, level=offer.level,
                           phone_install_id=offer.phone_install_id, accepted_at=now_iso())
    with _lock(store_root):
        rows = _rows(store_root)
        rows[accept.device_id] = {"computer_id": accept.computer_id, "level": accept.level,
                                  "phone_install_id": accept.phone_install_id,
                                  "accepted_at": accept.accepted_at}
        _write(store_root, rows)
    return accept


def forget_accept(store_root: Path | str, device_id: str) -> bool:
    with _lock(store_root):
        rows = _rows(store_root)
        existed = rows.pop(str(device_id or ""), None) is not None
        if existed:
            _write(store_root, rows)
    return existed


def list_accepts(store_root: Path | str) -> list[ReverseAccept]:
    """The accepted phones still paired here. A row whose pairing ended is dropped."""

    with _lock(store_root):
        rows = _rows(store_root)
        live: list[ReverseAccept] = []
        gone: list[str] = []
        for device_id, row in rows.items():
            # MUTATION: answer a row whose device was unpaired here and the unpair test
            # still lists the phone as accepted. MUTATION: drop the level check and
            # test_reverse_grant's retired-level test still lists a stored ``look`` accept.
            if row.get("level") not in GRANT_LEVELS or not _paired_here(store_root, device_id):
                gone.append(device_id)
                continue
            live.append(ReverseAccept(device_id=device_id, computer_id=str(row.get("computer_id") or ""),
                                      level=str(row["level"]),
                                      phone_install_id=str(row.get("phone_install_id") or ""),
                                      accepted_at=str(row.get("accepted_at") or "")))
        if gone:
            for device_id in gone:
                rows.pop(device_id, None)
            _write(store_root, rows)
    return sorted(live, key=lambda a: a.device_id)
