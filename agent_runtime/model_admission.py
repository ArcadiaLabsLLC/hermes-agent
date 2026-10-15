"""The one memory admission authority for every local model this Hermes loads.

Architecture §5.1 of the launcher's embedded-Hermes design (owner ruling
2026-09-28): bundled Hermes loads the speech models AND the local LLMs on a
desktop, so it owns the one GPU/RAM budget. Every load RESERVES here before it
touches memory and RELEASES after it unloads; a reservation that does not fit is
refused, or makes room by evicting an IDLE model that registered an evictor.
When full Hermes is the active install it still loads its own LLMs — it admits
them through bundled Hermes's ``runtime.admission.*`` methods
(:mod:`agent_runtime.model_admission_client`), so two processes never both say
yes to the same bytes.

Budgets come from upstream's hardware probe
(``hermes_cli.local_runtime.hardware.probe_budget(planning=True)``): a discrete
card gives a ``vram`` pool (total minus upstream's desktop margin) beside a
``ram`` pool; a machine with no discrete card (the mid-range CPU target) or a
unified-memory device has ONE pool, and a ``vram`` request lands in it.

Invariant: the fit check and the insert happen under one lock, and an evicted
model's bytes stay counted until its evictor has returned — so the sum of the
admitted reservations in a pool never exceeds the pool's capacity.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

__layer__ = "stores"

__all__ = [
    "AdmissionRefused",
    "ModelAdmission",
    "RESOURCES",
    "admission",
    "set_admission",
]

#: What a caller asks for. ``vram`` maps to the ``ram`` pool on a shared-memory machine.
RESOURCES = ("vram", "ram")
KINDS = ("stt", "tts", "llm")
OWNERS = ("local", "remote")

#: A remote holder (another process) renews by reserving again; one that stops renewing is
#: dropped after this long, so a crashed full Hermes cannot pin the budget forever.
DEFAULT_LEASE_SECONDS = 120.0
MAX_LEASE_SECONDS = 3600.0

#: Share of physical RAM a discrete-GPU machine lets models take (the OS, the Launcher and a
#: game keep the rest). A shared-memory machine uses upstream's own UMA headroom instead.
_RAM_POOL_FRACTION = 0.6

#: Eviction passes before a reserve gives up: each pass evicts every idle victim it picked.
_MAX_EVICTION_PASSES = 3


class AdmissionRefused(Exception):
    """A reservation the budget cannot hold. ``reason`` is the closed branch point."""

    def __init__(self, reason: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.reason, self.details = reason, details


@dataclass
class _Reservation:
    holder: str
    kind: str
    pool: str
    resource: str
    bytes: int
    owner: str
    evict: Callable[[], None] | None
    idle: bool
    last_used: float
    expires_at: float | None
    evicting: bool = field(default=False)

    def view(self, now: float) -> dict:
        return {"holder": self.holder, "kind": self.kind, "pool": self.pool, "resource": self.resource,
                "bytes": self.bytes, "owner": self.owner, "evictable": self.evict is not None,
                "idle": self.idle, "evicting": self.evicting,
                "lease_remaining_s": None if self.expires_at is None else max(0.0, round(self.expires_at - now, 1))}


def _probe_pools() -> tuple[dict[str, int], bool]:
    """Capacities from upstream's planning budget; one shared pool when there is no discrete card."""
    from hermes_cli.local_runtime.hardware import probe_budget

    budget = probe_budget(planning=True)
    if budget.uma or budget.ram_available_bytes <= 0:
        return {"ram": int(budget.usable_vram_bytes)}, True
    return {"vram": int(budget.usable_vram_bytes),
            "ram": int(budget.ram_available_bytes * _RAM_POOL_FRACTION)}, False


class ModelAdmission:
    """Reserve / release / evict against fixed pool capacities."""

    def __init__(self, pools: dict[str, int] | None = None, *, clock: Callable[[], float] = time.monotonic) -> None:
        if pools is None:
            pools, shared = _probe_pools()
        else:
            shared = "vram" not in pools
        if "ram" not in pools or any(type(v) is not int or v < 0 for v in pools.values()):
            raise ValueError("pools need a non-negative integer 'ram' capacity")
        self._pools = dict(pools)
        self.shared = shared
        self._clock = clock
        self._lock = threading.Lock()
        self._held: dict[str, _Reservation] = {}
        self.refusals = 0
        self.evictions = 0

    # ── reads ────────────────────────────────────────────────────────────

    def pool_for(self, resource: str) -> str:
        if resource not in RESOURCES:
            raise AdmissionRefused("resource_invalid", f"resource must be one of {RESOURCES}", resource=resource)
        return resource if resource in self._pools else "ram"

    def _used(self, pool: str, *, excluding: str | None = None) -> int:
        return sum(r.bytes for r in self._held.values() if r.pool == pool and r.holder != excluding)

    def _expire(self, now: float) -> None:
        for holder in [h for h, r in self._held.items() if r.expires_at is not None and r.expires_at <= now]:
            del self._held[holder]

    def status(self) -> dict:
        with self._lock:
            now = self._clock()
            self._expire(now)
            return {"shared_memory": self.shared,
                    "pools": {name: {"capacity_bytes": cap, "reserved_bytes": self._used(name)}
                              for name, cap in sorted(self._pools.items())},
                    "reservations": [r.view(now) for r in sorted(self._held.values(), key=lambda r: r.holder)],
                    "refusals": self.refusals, "evictions": self.evictions}

    def holds(self, holder: str) -> bool:
        with self._lock:
            return holder in self._held

    # ── writes ───────────────────────────────────────────────────────────

    def reserve(self, holder: str, *, kind: str, resource: str, bytes: int,
                evict: Callable[[], None] | None = None, owner: str = "local",
                lease_seconds: float | None = None) -> dict:
        """Admit ``bytes`` for ``holder`` or raise :class:`AdmissionRefused`.

        Re-reserving a held ``holder`` replaces its row (a remote renew, or a resize); its old
        bytes do not count against the new request. ``evict`` makes the reservation evictable
        while it is idle: it must unload the model, and it runs WITHOUT this lock held.
        """
        if not isinstance(holder, str) or not holder or len(holder) > 200:
            raise AdmissionRefused("holder_invalid", "holder must be a non-empty string (<=200 chars)")
        if kind not in KINDS:
            raise AdmissionRefused("kind_invalid", f"kind must be one of {KINDS}", kind=kind)
        if owner not in OWNERS:
            raise AdmissionRefused("owner_invalid", f"owner must be one of {OWNERS}")
        if type(bytes) is not int or bytes < 0:
            raise AdmissionRefused("bytes_invalid", "bytes must be a non-negative integer")
        pool = self.pool_for(resource)
        if owner == "remote":
            lease = DEFAULT_LEASE_SECONDS if lease_seconds is None else float(lease_seconds)
            if not 0 < lease <= MAX_LEASE_SECONDS:
                raise AdmissionRefused("lease_invalid", f"lease_seconds must be in (0, {MAX_LEASE_SECONDS:g}]")
        else:
            lease = None
        for _pass in range(_MAX_EVICTION_PASSES + 1):
            with self._lock:
                now = self._clock()
                self._expire(now)
                capacity = self._pools[pool]
                used = self._used(pool, excluding=holder)
                if used + bytes <= capacity:
                    self._held[holder] = _Reservation(
                        holder=holder, kind=kind, pool=pool, resource=resource, bytes=bytes, owner=owner,
                        evict=evict, idle=False, last_used=now,
                        expires_at=None if lease is None else now + lease)
                    return {"holder": holder, "pool": pool, "bytes": bytes, "capacity_bytes": capacity,
                            "reserved_bytes": used + bytes,
                            "lease_seconds": lease}
                victims = self._pick_victims(pool, used + bytes - capacity, exclude=holder)
                if victims is None or _pass == _MAX_EVICTION_PASSES:
                    self.refusals += 1
                    raise AdmissionRefused(
                        "over_budget", f"{kind} model needs {bytes} bytes; {pool} pool has "
                        f"{max(0, capacity - used)} of {capacity} free",
                        pool=pool, requested_bytes=bytes, capacity_bytes=capacity, reserved_bytes=used,
                        holders=[r.view(now) for r in self._held.values() if r.pool == pool])
                for victim in victims:
                    victim.evicting = True
            self._evict(victims)
        raise AssertionError("unreachable")  # pragma: no cover

    def _pick_victims(self, pool: str, shortfall: int, *, exclude: str) -> list[_Reservation] | None:
        """Least-recently-used idle evictable holders covering ``shortfall``, or None if they cannot."""
        candidates = sorted((r for r in self._held.values()
                             if r.pool == pool and r.holder != exclude and r.idle
                             and r.evict is not None and not r.evicting),
                            key=lambda r: r.last_used)
        picked, freed = [], 0
        for reservation in candidates:
            if freed >= shortfall:
                break
            picked.append(reservation)
            freed += reservation.bytes
        return picked if freed >= shortfall else None

    def _evict(self, victims: list[_Reservation]) -> None:
        for victim in victims:
            try:
                victim.evict()
            except Exception:  # noqa: BLE001 - a failed unload keeps its bytes counted
                with self._lock:
                    if self._held.get(victim.holder) is victim:
                        victim.evicting = False
                continue
            with self._lock:
                if self._held.get(victim.holder) is victim:
                    del self._held[victim.holder]
                self.evictions += 1

    def release(self, holder: str) -> bool:
        with self._lock:
            return self._held.pop(holder, None) is not None

    def mark(self, holder: str, *, idle: bool) -> None:
        """A local holder says whether it is in use; only an idle holder can be evicted."""
        with self._lock:
            reservation = self._held.get(holder)
            if reservation is not None:
                reservation.idle = idle
                reservation.last_used = self._clock()


_lock = threading.Lock()
_admission: ModelAdmission | None = None


def admission() -> ModelAdmission:
    """The process's one authority, built from the hardware probe on first use."""
    global _admission
    with _lock:
        if _admission is None:
            _admission = ModelAdmission()
        return _admission


def set_admission(value: ModelAdmission | None) -> None:
    """Install a fixed-budget authority (tests, or a host that knows its budget); None rebuilds."""
    global _admission
    with _lock:
        _admission = value
