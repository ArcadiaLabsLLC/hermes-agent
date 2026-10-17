"""Lens source credentials: opaque references resolved from the hermes credential pool.

Launcher plan ``EterniaLauncher/docs/companion/planned/MONITORING_CREDENTIALS_SEPARATION_2026-10-15.md``
S2 (owner-approved 2026-10-15) and Lens plan W12:

* A manifest names a credential by ``credential_ref`` only; the bytes live in the
  hermes credential pool (``auth.json`` ``credential_pool``), under one provider
  slice, :data:`LENS_POOL_PROVIDER`, keyed by the reference.
* Scope is the PERSONA HOME (the serve's ``HERMES_HOME``, resolved at call time).
  The pool's profile reader falls back to the global root per provider; a row is
  therefore stamped with a digest of the home that wrote it, and a row read from
  another home is treated as absent — a second persona never sees the first's
  password.
* Write-only from the outside: :func:`set_credential` writes, :func:`credential_status`
  reports set / rotated-at, and only :func:`resolve_credential` returns the value —
  to a source, per read, in-process. Nothing here logs, returns or stores a value
  anywhere else, and :class:`LensCredential` never prints it.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone, UTC
from enum import Enum
from typing import Any

from .wire_value import bounded_string, format_utc, opaque_id

__layer__ = "stores"

#: The one credential-pool provider slice Lens writes.
LENS_POOL_PROVIDER = "lens"
_SOURCE = "manual:lens"
#: The longest secret accepted (a bearer token or a password).
MAXIMUM_SECRET_BYTES = 8192


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


def _home_digest() -> str:
    from hermes_constants import get_hermes_home

    return hashlib.sha256(str(get_hermes_home().resolve()).encode("utf-8")).hexdigest()[:24]


def _rows() -> list[dict[str, Any]]:
    from hermes_cli.auth import read_credential_pool

    return [row for row in read_credential_pool(LENS_POOL_PROVIDER) if isinstance(row, dict)]


def _own_row(ref: str) -> dict[str, Any] | None:
    home = _home_digest()
    for row in _rows():
        if row.get("id") == ref and row.get("lens_home") == home:
            return row
    return None


def set_credential(ref: str, *, scheme: str, secret: str, username: str | None = None,
                   now: datetime | None = None) -> dict[str, Any]:
    """Write (or rotate) ``ref`` in this home's pool. Returns its status, never the value."""

    from hermes_cli.auth import write_credential_pool

    ref = opaque_id(ref)
    kind = CredentialScheme(scheme)
    secret = bounded_string(secret, maximum=MAXIMUM_SECRET_BYTES)
    if kind is CredentialScheme.BASIC:
        username = bounded_string(username or "", maximum=256, empty=True)
    else:
        username = None
    stamp = format_utc(now or datetime.now(UTC))
    row = {
        "id": ref, "label": f"lens:{ref}", "auth_type": "api_key", "priority": 0, "source": _SOURCE,
        "access_token": secret, "lens_scheme": kind.value, "lens_home": _home_digest(), "lens_rotated_at": stamp,
    }
    if username is not None:
        row["lens_username"] = username
    others = [r for r in _rows() if r.get("id") != ref]
    write_credential_pool(LENS_POOL_PROVIDER, [*others, row])
    return credential_status(ref)


def credential_status(ref: str) -> dict[str, Any]:
    """``{ref, set, rotated_at}`` — presence and rotation only (the Launcher's write-only view)."""

    row = _own_row(opaque_id(ref))
    return {"ref": ref, "set": row is not None, "rotated_at": None if row is None else row.get("lens_rotated_at")}


def resolve_credential(ref: str) -> LensCredential | None:
    """The credential for one read, or None when this home holds no such reference."""

    row = _own_row(opaque_id(ref))
    if row is None or not isinstance(row.get("access_token"), str) or not row["access_token"]:
        return None
    try:
        scheme = CredentialScheme(row.get("lens_scheme"))
    except ValueError:
        return None
    return LensCredential(ref=ref, scheme=scheme, secret=row["access_token"], username=row.get("lens_username"))
