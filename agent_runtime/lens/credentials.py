"""Lens source credentials: opaque references resolved from a fork-owned 0600 file.

Launcher plan ``EterniaLauncher/docs/companion/planned/MONITORING_CREDENTIALS_SEPARATION_2026-10-15.md``
S2 as amended by the owner ruling of 2026-10-18 (``RT-LENS-CREDENTIAL-PREVIEW``),
and Lens plan W12:

* A manifest names a credential by ``credential_ref`` only; the bytes live in ONE
  fork-owned file, ``<head home>/lens/credentials.json``, written 0600
  (:func:`credentials_path`). They are NOT in the hermes credential pool: upstream's
  dashboard lists every pool slice with a token preview, and the Lens ruling is
  write-only — set / not set / rotated, never any part of the value.
* Scope is the PERSONA HOME (the serve's ``HERMES_HOME``, resolved at call time): the
  file lives under the home, so a second persona never sees the first's password.
* Write-only from the outside: :func:`set_credential` writes, :func:`credential_status`
  reports set / rotated-at, and only :func:`resolve_credential` returns the value —
  to a source, per read, in-process. Nothing here logs, returns or stores a value
  anywhere else, and :class:`LensCredential` never prints it.
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
from typing import Any

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


def set_credential(ref: str, *, scheme: str, secret: str, username: str | None = None,
                   now: datetime | None = None) -> dict[str, Any]:
    """Write (or rotate) ``ref`` in this home's file. Returns its status, never the value."""

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
    with _LOCK:
        rows = _read_credentials_file()
        rows[ref] = row
        _write_file(rows)
    return credential_status(ref)


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


def credential_status(ref: str) -> dict[str, Any]:
    """``{ref, set, rotated_at}`` — presence and rotation only (the Launcher's write-only view)."""

    row = _own_row(opaque_id(ref))
    return {"ref": ref, "set": row is not None, "rotated_at": None if row is None else row.get("rotated_at")}


def resolve_credential(ref: str) -> LensCredential | None:
    """The credential for one read, or None when this home holds no such reference."""

    row = _own_row(opaque_id(ref))
    if row is None or not isinstance(row.get("secret"), str) or not row["secret"]:
        return None
    try:
        scheme = CredentialScheme(row.get("scheme"))
    except ValueError:
        return None
    return LensCredential(ref=ref, scheme=scheme, secret=row["secret"], username=row.get("username"))
