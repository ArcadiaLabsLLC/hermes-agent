"""Lens source credentials: opaque references resolved from a fork-owned 0600 file.

Launcher plan ``EterniaLauncher/docs/companion/subsystems/MONITORING_CREDENTIALS_SEPARATION_2026-10-15.md``
S2 as amended by the owner ruling of 2026-10-18 (``RT-LENS-CREDENTIAL-PREVIEW``),
and Lens plan W12:

* A manifest names a credential by ``credential_ref`` only; the bytes live in ONE
  fork-owned file, ``<head home>/lens/credentials.json``, written 0600
  (:func:`credentials_path`). They are NOT in the hermes credential pool: upstream's
  dashboard lists every pool slice with a token preview, and the Lens ruling is
  write-only — set / not set / rotated, never any part of the value.
* Scope is the runtime HEAD HOME, resolved at call time through ``lens_root()``:
  persona tools and the serve resolve the same file; separate head homes remain isolated.
* Write-only from the outside: :func:`set_credential` writes, :func:`credential_status`
  reports set / rotated-at, and only :func:`resolve_credential` returns the value —
  to a source, per read, in-process. Nothing here logs, returns or stores a value
  anywhere else, and :class:`LensCredential` never prints it.
* **A credential is saved for ONE address and is only ever sent there**
  (``RT-LENS-CREDENTIAL-NOT-BOUND-TO-A-HOST``). Its row records ``host`` — scheme, name and
  port (:func:`credential_host`) — and BOTH readers of a row (:func:`resolve_credential`,
  :func:`credential_status`) take the address the caller is about to use and answer through
  one predicate (:func:`_saved_for`): a different address is :attr:`CredentialRefusal.HOST_MISMATCH`,
  never the value. The address is never the request's word: ``runtime.lens.credential.set``
  reads it off the monitors that name the ref (:func:`sign_in_host`). An ingress route's
  secret is saved for no address (``host=None``) and only the door reads it.
  **A row an earlier build wrote has no ``host`` and fails closed**: it reads as not signed in
  for every address until the person saves it again (it still serves as a route's secret,
  which is sent nowhere).
* One-way migration: values an earlier build wrote to the pool's ``lens`` slice
  (stamped with this home's digest) are moved into the file and removed from the
  pool the first time this home's credentials are touched (:func:`migrate_pool_slice`).
  Nothing ever writes the pool slice again.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .feed import address_parts, feed_address
from .wire_value import bounded_string, format_utc, opaque_id

__layer__ = "stores"

#: The credential-pool provider slice earlier builds wrote; read once, to migrate out.
LEGACY_POOL_PROVIDER = "lens"
_FILE_VERSION = 1
#: The longest secret accepted (a bearer token or a password).
MAXIMUM_SECRET_BYTES = 8192

_LOCK = threading.Lock()
#: Homes whose pool slice has been migrated in this process (resolved paths).
_MIGRATED: set[str] = set()


class CredentialScheme(str, Enum):
    BEARER = "bearer"
    BASIC = "basic"


class CredentialRefusal(str, Enum):
    """Why a read gets no credential. The values are ``ReadReason`` values (``sources``)."""

    MISSING = "credential_missing"
    HOST_MISMATCH = "credential_host_mismatch"


#: The host of a feed whose kind sends nowhere: equal to no saved address, so it holds no credential.
NO_ADDRESS = ""


def credential_host(url: str) -> str:
    """``scheme://name:port`` of an http(s) address — what a credential is saved for. The port is
    always written, so ``https://a`` and ``https://a:443`` are one address and ``:8443`` another."""

    scheme, name, port = address_parts(url)
    return f"{scheme}://{name}:{port}"


def feed_host(feed: dict[str, Any]) -> str:
    """The address ``feed``'s credential must be saved for (:data:`NO_ADDRESS` when it sends nowhere)."""

    address = feed_address(feed)
    return NO_ADDRESS if address is None else credential_host(address)


def sign_in_host(ref: str, manifests: Iterable[dict[str, Any]]) -> str:
    """The one address the feeds naming ``ref`` in ``manifests`` read — what a sign-in is saved for.

    Refused ``credential_host_unknown`` when no feed names the ref and
    ``credential_host_ambiguous`` when they read several addresses: a secret is never saved for
    an address nobody chose, and never for a guess between two."""

    from .store import LensStoreError, StoreRefusal

    hosts = {feed_host(feed) for manifest in manifests for feed in manifest["feeds"]
             if feed.get("credential_ref") == ref} - {NO_ADDRESS}
    if len(hosts) != 1:
        raise LensStoreError(StoreRefusal.CREDENTIAL_HOST_AMBIGUOUS if hosts else StoreRefusal.CREDENTIAL_HOST_UNKNOWN)
    return hosts.pop()


@dataclass(frozen=True, slots=True)
class LensCredential:
    ref: str
    scheme: CredentialScheme
    secret: str = field(repr=False)
    username: str | None = None

    def headers(self) -> dict[str, str]:
        if self.scheme is CredentialScheme.BEARER:
            return {"Authorization": f"Bearer {self.secret}"}
        pair = f"{self.username or ''}:{self.secret}".encode()
        return {"Authorization": "Basic " + base64.b64encode(pair).decode("ascii")}

    def secret_forms(self) -> tuple[str, ...]:
        """Every spelling of the secret a redaction check must look for."""

        forms = [self.secret, base64.b64encode(self.secret.encode()).decode("ascii")]
        if self.scheme is CredentialScheme.BASIC:
            forms.append(self.headers()["Authorization"].split(" ", 1)[1])
        return tuple(forms)


def _home() -> Path:
    """The home whose ``lens/`` holds the credentials file: the one Lens root's parent."""

    from .store import lens_root

    return lens_root().parent.resolve()


def credentials_path() -> Path:
    """``<head home>/lens/credentials.json`` — resolved at call time."""

    return _home() / "lens" / "credentials.json"


def _read_credentials_file() -> dict[str, dict[str, Any]]:
    try:
        document = json.loads(credentials_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = document.get("credentials") if isinstance(document, dict) else None
    return {ref: row for ref, row in (rows or {}).items() if isinstance(row, dict)}


def _write_file(rows: dict[str, dict[str, Any]]) -> None:
    from utils import atomic_json_write

    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, {"version": _FILE_VERSION, "credentials": rows}, indent=2, sort_keys=True, mode=0o600)


def _legacy_home_digest(home: Path) -> str:
    """The stamp earlier builds put on a pool row (``lens_home``): this home's path digest."""

    return hashlib.sha256(str(home).encode("utf-8")).hexdigest()[:24]


def migrate_pool_slice() -> int:
    """Move this home's rows out of the pool's ``lens`` slice into the file. One way; idempotent.

    A ref already in the file keeps the file's value (it is the newer write). Returns
    how many pool rows were removed."""

    home = _home()
    if str(home) in _MIGRATED:
        return 0
    from hermes_cli.auth import read_credential_pool, write_credential_pool

    with _LOCK:
        stamp = _legacy_home_digest(home)
        legacy = [row for row in read_credential_pool(LEGACY_POOL_PROVIDER)
                  if isinstance(row, dict) and row.get("lens_home") == stamp and isinstance(row.get("id"), str)]
        if legacy:
            rows = _read_credentials_file()
            for row in legacy:
                secret = row.get("access_token")
                if row["id"] in rows or not isinstance(secret, str) or not secret:
                    continue
                moved = {"scheme": row.get("lens_scheme"), "secret": secret, "rotated_at": row.get("lens_rotated_at")}
                if row.get("lens_username") is not None:
                    moved["username"] = row["lens_username"]
                rows[row["id"]] = moved
            _write_file(rows)  # the file first: a crash between the two leaves a duplicate, never a loss
            write_credential_pool(LEGACY_POOL_PROVIDER, [], removed_ids=[row["id"] for row in legacy])
        _MIGRATED.add(str(home))
        return len(legacy)


def _own_row(ref: str) -> dict[str, Any] | None:
    migrate_pool_slice()
    return _read_credentials_file().get(ref)


def set_credential(ref: str, *, scheme: str, secret: str, host: str | None, username: str | None = None,
                   now: datetime | None = None) -> dict[str, Any]:
    """Write (or rotate) ``ref`` in this home's file, saved for ``host`` (:func:`credential_host`;
    None for an ingress route's secret, which is sent nowhere). Returns its status, never the value."""

    ref = opaque_id(ref)
    kind = CredentialScheme(scheme)
    secret = bounded_string(secret, maximum=MAXIMUM_SECRET_BYTES)
    if kind is CredentialScheme.BASIC:
        username = bounded_string(username or "", maximum=256, empty=True)
    else:
        username = None
    migrate_pool_slice()
    row: dict[str, Any] = {"scheme": kind.value, "secret": secret, "rotated_at": format_utc(now or datetime.now(UTC))}
    if username is not None:
        row["username"] = username
    if host is not None:
        row["host"] = host
    with _LOCK:
        rows = _read_credentials_file()
        rows[ref] = row
        _write_file(rows)
    return credential_status(ref, host=host)


def forget_credential(ref: str) -> bool:
    """Remove ``ref`` from this home's file (a revoked ingress route's secret). True when it was there."""

    ref = opaque_id(ref)
    migrate_pool_slice()
    with _LOCK:
        rows = _read_credentials_file()
        if rows.pop(ref, None) is None:
            return False
        _write_file(rows)
    return True


def _saved_for(ref: str, host: str | None) -> tuple[dict[str, Any] | None, CredentialRefusal | None]:
    """``(row, refusal)``: this home's row for ``ref`` and why a caller at ``host`` may not use it
    (None when it may). The ONE place a saved address meets the address about to be used."""

    row = _own_row(opaque_id(ref))
    if row is None or not isinstance(row.get("secret"), str) or not row["secret"]:
        return None, CredentialRefusal.MISSING
    return row, None if row.get("host") == host else CredentialRefusal.HOST_MISMATCH


def credential_status(ref: str, *, host: str | None) -> dict[str, Any]:
    """``{ref, set, rotated_at, host}`` for a caller at ``host`` — presence and rotation only (the
    Launcher's write-only view). ``set`` is true only when the value would be sent to ``host``;
    ``host`` is the address it is saved for (null: none, or saved before addresses were recorded)."""

    row, refusal = _saved_for(ref, host)
    return {"ref": ref, "set": refusal is None, "rotated_at": None if row is None else row.get("rotated_at"),
            "host": None if row is None else row.get("host")}


def resolve_credential(ref: str, *, host: str | None) -> LensCredential | CredentialRefusal:
    """The credential for one read at ``host`` (None: an ingress route's own secret), or why not."""

    row, refusal = _saved_for(ref, host)
    if refusal is not None:
        return refusal
    try:
        scheme = CredentialScheme(row.get("scheme"))
    except ValueError:
        return CredentialRefusal.MISSING
    return LensCredential(ref=ref, scheme=scheme, secret=row["secret"], username=row.get("username"))
