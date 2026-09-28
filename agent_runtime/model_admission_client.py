"""Admit a local model load through BUNDLED Hermes's budget, from another Hermes process.

Architecture §5.1: when full Hermes is the active install it runs its own LLMs
while bundled Hermes serves speech, so full Hermes reserves through bundled
Hermes's ``runtime.admission.*`` before it loads and releases after it unloads.
Reporting loads to each other is not enough — two admitters both say yes.

The client is transport-agnostic: it takes ``call(method, params) -> frame``.
:meth:`BundledAdmissionClient.over_socket` builds that from a connected,
greeted :class:`agent_runtime.serve_socket.client.ServeSocketClient`.
A reservation is a lease; :class:`AdmissionLease` renews it in the background
for as long as the model stays loaded.
"""

from __future__ import annotations

import itertools
import threading
from typing import Any, Callable

from agent_runtime.model_admission import DEFAULT_LEASE_SECONDS, AdmissionRefused

__layer__ = "lanes"

__all__ = ["AdmissionLease", "BundledAdmissionClient"]

Call = Callable[[str, dict], dict]


class BundledAdmissionClient:
    def __init__(self, call: Call) -> None:
        self._call = call

    @classmethod
    def over_socket(cls, connection: Any) -> "BundledAdmissionClient":
        """``connection``: a greeted ``ServeSocketClient``. Notifications are skipped until the reply."""
        ids = itertools.count(1)
        lock = threading.Lock()

        def call(method_name: str, params: dict) -> dict:
            with lock:
                rid = f"admission-{next(ids)}"
                connection.send({"jsonrpc": "2.0", "id": rid, "method": method_name, "params": params})
                while True:
                    frame = connection.read_frame()
                    if frame is None:
                        raise ConnectionError("bundled Hermes closed the connection")
                    if frame.get("id") == rid:
                        return frame

        return cls(call)

    def _result(self, method_name: str, params: dict) -> dict:
        frame = self._call(method_name, params)
        if "error" in frame:
            error = frame["error"]
            data = dict(error.get("data") or {})
            reason = data.pop("reason", "refused")
            raise AdmissionRefused(reason, error.get("message", reason), **data)
        return frame["result"]

    def status(self) -> dict:
        return self._result("runtime.admission.status", {})

    def reserve(self, holder: str, *, bytes: int, resource: str, kind: str = "llm",
                lease_seconds: float = DEFAULT_LEASE_SECONDS) -> dict:
        """Admit before loading; raises :class:`AdmissionRefused` (``over_budget`` …) instead."""
        return self._result("runtime.admission.reserve", {"holder": holder, "kind": kind, "resource": resource,
                                                          "bytes": bytes, "lease_seconds": lease_seconds})

    def release(self, holder: str) -> bool:
        return bool(self._result("runtime.admission.release", {"holder": holder})["released"])

    def lease(self, holder: str, *, bytes: int, resource: str, kind: str = "llm",
              lease_seconds: float = DEFAULT_LEASE_SECONDS) -> "AdmissionLease":
        """Reserve now and keep renewing until :meth:`AdmissionLease.release` (or ``with`` exit)."""
        self.reserve(holder, bytes=bytes, resource=resource, kind=kind, lease_seconds=lease_seconds)
        return AdmissionLease(self, holder, bytes=bytes, resource=resource, kind=kind, lease_seconds=lease_seconds)


class AdmissionLease:
    """A held reservation renewed at half its lease. A failed renewal is recorded, never raised:
    the model is already loaded, and the owner reads :attr:`renew_error` to decide whether to unload."""

    def __init__(self, client: BundledAdmissionClient, holder: str, *, bytes: int, resource: str, kind: str,
                 lease_seconds: float) -> None:
        self.client, self.holder = client, holder
        self._args = {"bytes": bytes, "resource": resource, "kind": kind, "lease_seconds": lease_seconds}
        self._stop = threading.Event()
        self.renew_error: Exception | None = None
        self._thread = threading.Thread(target=self._renew, args=(lease_seconds / 2,), daemon=True,
                                        name=f"admission-lease-{holder}")
        self._thread.start()

    def _renew(self, every: float) -> None:
        while not self._stop.wait(every):
            try:
                self.client.reserve(self.holder, **self._args)
                self.renew_error = None
            except Exception as exc:  # noqa: BLE001 - recorded for the owner
                self.renew_error = exc

    def release(self) -> bool:
        self._stop.set()
        self._thread.join(timeout=5)
        return self.client.release(self.holder)

    def __enter__(self) -> "AdmissionLease":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()
