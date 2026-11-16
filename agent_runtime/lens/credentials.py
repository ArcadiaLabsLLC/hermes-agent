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
* **A name holds one sign-in PER ADDRESS** (``RT-LENS-UPDATE-MOVED-SITE-CANNOT-SIGN-IN-BEFORE-SEAL``,
  ruled 2026-11-15). ``credentials[ref]`` is a list of rows, one per saved address, so the draft
  of a monitor's next revision that moves a source to another site is signed in BEFORE Seal
  while the sealed revision keeps reading with the sign-in made for its own site. Which address
  a save is for is still the store's word: ``runtime.lens.credential.set`` names a monitor and
  which of its two manifests (:class:`SignInRevision`), and :func:`revision_manifest` hands
  :func:`sign_in_host` that one manifest; with neither it reads every live manifest, as before.
  :func:`set_credential` replaces the row of its own address and, given ``live_hosts``, forgets
  the rows of addresses no live manifest names any more (a site a sealed update moved away
  from), so a name never gathers secrets nobody reads. Rejected: a fresh ref name for the moved
  feed (the person, or Add, would rewrite a draft to sign it in, and every move leaves a dead
  name), replacing the one row before Seal (the sealed revision goes dark), and holding the
  new secret beside the draft until Seal (a second credential store).
  A file an earlier build wrote (``version`` 1, one row per name) reads as a one-row list; an
  earlier build reading this file sees no row and fails closed.
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
_FILE_VERSION = 2
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


class SignInRevision(str, Enum):
    """Which of a monitor's two manifests a sign-in is for (``credential.set``'s ``revision``)."""

    SEALED = "sealed"
    DRAFT = "draft"


def revision_manifest(monitor: dict[str, Any], revision: SignInRevision) -> dict[str, Any]:
    """The manifest of ``monitor`` (a ``LensStore`` summary) a sign-in for ``revision`` reads its
    address off. Refused ``monitor_retired``, and ``not_sealed`` / ``no_draft`` when it holds none."""

    from .store import LensStoreError, MonitorState, StoreRefusal

    held = {SignInRevision.SEALED: ((monitor["sealed"] or {}).get("manifest"), StoreRefusal.NOT_SEALED),
            SignInRevision.DRAFT: (monitor["draft"], StoreRefusal.NO_DRAFT)}
    manifest, absent = held[revision]
    if monitor["state"] == MonitorState.RETIRED.value:
        raise LensStoreError(StoreRefusal.RETIRED)
    if manifest is None:
        raise LensStoreError(absent)
    return manifest


def named_hosts(ref: str, manifests: Iterable[dict[str, Any]]) -> set[str]:
    """Every address the feeds naming ``ref`` in ``manifests`` read."""

    return {feed_host(feed) for manifest in manifests for feed in manifest["feeds"]
            if feed.get("credential_ref") == ref} - {NO_ADDRESS}


def sign_in_host(ref: str, manifests: Iterable[dict[str, Any]]) -> str:
    """The one address the feeds naming ``ref`` in ``manifests`` read — what a sign-in is saved for.

    Refused ``credential_host_unknown`` when no feed names the ref and
    ``credential_host_ambiguous`` when they read several addresses: a secret is never saved for
    an address nobody chose, and never for a guess between two."""

    from .store import LensStoreError, StoreRefusal

    hosts = named_hosts(ref, manifests)
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


def _read_credentials_file() -> dict[str, list[dict[str, Any]]]:
    """``{ref: [row per saved address]}``. A ``version`` 1 file held one row per name: a one-row list."""

    try:
        document = json.loads(credentials_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    held = document.get("credentials") if isinstance(document, dict) else None
    return {ref: [row for row in (rows if isinstance(rows, list) else [rows]) if isinstance(row, dict)]
            for ref, rows in (held or {}).items()}


def _write_file(rows: dict[str, list[dict[str, Any]]]) -> None:
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
                rows[row["id"]] = [moved]
            _write_file(rows)  # the file first: a crash between the two leaves a duplicate, never a loss
            write_credential_pool(LEGACY_POOL_PROVIDER, [], removed_ids=[row["id"] for row in legacy])
        _MIGRATED.add(str(home))
        return len(legacy)


def _own_rows(ref: str) -> list[dict[str, Any]]:
    """This home's usable rows for ``ref`` (one per saved address), oldest save first."""

    migrate_pool_slice()
    return [row for row in _read_credentials_file().get(ref, [])
            if isinstance(row.get("secret"), str) and row["secret"]]


def set_credential(ref: str, *, scheme: str, secret: str, host: str | None, username: str | None = None,
                   now: datetime | None = None, live_hosts: Iterable[str] | None = None) -> dict[str, Any]:
    """Write (or rotate) ``ref``'s sign-in for ``host`` in this home's file (:func:`credential_host`;
    None for an ingress route's secret, which is sent nowhere). The name's rows for other addresses
    stay, except — given ``live_hosts``, the addresses live manifests name it at — the ones for an
    address outside them, which nothing reads any more. Returns its status, never the value."""

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
    kept = None if live_hosts is None else set(live_hosts)
    with _LOCK:
        rows = _read_credentials_file()
        rows[ref] = [other for other in rows.get(ref, [])
                     if other.get("host") != host and (kept is None or other.get("host") in kept)] + [row]
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
    (None when it may). The ONE place a saved address meets the address about to be used: the
    row saved for exactly ``host``, else the name's newest row with ``credential_host_mismatch``."""

    rows = _own_rows(opaque_id(ref))
    for row in rows:
        if row.get("host") == host:
            return row, None
    return (rows[-1], CredentialRefusal.HOST_MISMATCH) if rows else (None, CredentialRefusal.MISSING)


def credential_status(ref: str, *, host: str | None) -> dict[str, Any]:
    """``{ref, set, rotated_at, host}`` for a caller at ``host`` — presence and rotation only (the
    Launcher's write-only view). ``set`` is true only when the value would be sent to ``host``;
    ``host`` is the address it is saved for (null: none, or saved before addresses were recorded;
    when ``set`` is false and the name is saved elsewhere, the address of its newest sign-in)."""

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
