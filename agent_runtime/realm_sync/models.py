"""Realm sync's value types and the constants every other module reads.

The error, the artifact, the membership boundary, the secret/state path sets and
the ``.gitattributes`` pin. A leaf: it imports nothing from this package, so the
appliers that import back into realm sync (``profile_artifact_sync``,
``realm_membership``, ``sync_admission``) land on a module that imports no applier.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

from .. import paths
from ..machine_roots import MACHINE_ROOTS_FILENAME
from ..models import Realm
from ..sync_text import canonicalize_text_bytes

__layer__ = "models"
__all__ = [
    "BASE_PROFILE_NAME",
    "HARD_EXCLUDED_PATH_PARTS",
    "MembershipDecision",
    "RealmMembershipProvider",
    "RealmSyncArtifact",
    "RealmSyncError",
    "SECRET_PATH_MARKERS",
    "_REALM_SYNC_GITATTRIBUTES",
    "_REALM_SYNC_GITATTRIBUTES_MARKER",
    "_canonicalize_text_bytes",
    "_safe_display_path",
]


SECRET_PATH_MARKERS = {
    ".env",
    "auth.json",
    "credentials",
    "credential",
    "creds",
    "oauth",
    "private_key",
    "secret",
    "secrets",
    "state.db",
    "token",
    "tokens",
}
# The machine seed every free Hermes profile forks from. Its RAW settings never
# travel through realm sync (Office layout realm-sync plan §5.1) — only the
# allowlisted persona definitions bound to it do. Same spelling as
# the historical base persona id; kept as its own constant here because the guard
# is about the profile HOME, which is what the original persona-id guard missed.
BASE_PROFILE_NAME = "base"
HARD_EXCLUDED_PATH_PARTS = {
    "blueprints",
    "blueprint_runs",
    # The machine-root registry binds logical roots to absolute paths on THIS
    # box. It is the half of the portable-config split that must never travel —
    # publishing it would push one member's drive layout onto everyone else.
    MACHINE_ROOTS_FILENAME,
    "proofs",
    "runs",
    "state.db",
    "worker_sessions",
}
# ``SECRET_ASSIGNMENT_RE`` — the publish gate's secret rule — is imported from
# ``agent_runtime.redaction``, the ONE home for every spelling of "secret-ish
# key + separator + value". Read the header there for the JSON blind spot that
# consolidation retired (``{"token": "…"}`` matched none of the twelve
# copies). It stays re-exported from this module under its historical name, so
# ``office_store``/``sync_admission`` keep importing it from here; both may now
# do so eagerly if they wish, since ``redaction`` is stdlib-only and carries
# none of this module's weight.

# Canonical line-ending policy for the realm sync repo. The publisher already
# canonicalizes every artifact to LF (see ``_canonicalize_text_bytes``); this
# repo-root ``.gitattributes`` makes member clones keep LF on checkout no matter
# what their local ``core.autocrlf`` is set to, so nobody re-flips the endings.
# ``text=auto`` leaves binary assets (skill PNG/JPG/… ) untouched. It is never an
# artifact, so it neither enters the artifact manifest nor the secret scanner.
_REALM_SYNC_GITATTRIBUTES = (
    "# Realm sync canonical line endings (managed by agent_runtime/realm_sync.py).\n"
    "# Published artifacts are written LF by the publisher; pin eol=lf so member\n"
    "# clones never re-flip endings on checkout regardless of local core.autocrlf.\n"
    "# text=auto leaves binary assets untouched.\n"
    "* text=auto eol=lf\n"
)
_REALM_SYNC_GITATTRIBUTES_MARKER = b"managed by agent_runtime/realm_sync.py"


class RealmSyncError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False, safe_details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.safe_details = safe_details or {}


@dataclass(frozen=True, slots=True)
class RealmSyncArtifact:
    kind: str
    source: Path
    relative_path: str
    destination: Path
    #: Synthesized published bytes. When set, THESE are what publish writes and
    #: ``source`` degrades to provenance (the file the projection was derived
    #: from). Added for the portable persona-config projection: the one artifact
    #: family that must never ship a raw file verbatim still rides the single
    #: publish lane — manifest, secret scan, EOL canonicalization, change
    #: detection — instead of growing a side channel.
    content: bytes | None = None
    #: The persona this artifact was resolved FOR, when it has one. Attribution
    #: only, never authority. ``sync_artifacts_for_workspace_agent`` used to
    #: infer it from a ``/<persona_token>/`` substring of the published path; the
    #: profile-file family publishes at a destination-shaped path
    #: (``store/profile_files/<profile>/…``) where that token no longer appears,
    #: so attribution is carried explicitly instead of guessed.
    persona_id: str | None = None

    def read_bytes(self) -> bytes:
        """The bytes this artifact publishes: synthesized content when present,
        otherwise the source file. Every publish-side reader MUST go through
        here — reading ``source`` directly would publish the raw file a
        synthesized artifact exists precisely to avoid."""

        if self.content is not None:
            return self.content
        return self.source.read_bytes()

    def row(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "path": self.relative_path.replace("\\", "/"),
            "destination": _safe_display_path(self.destination),
        }


@dataclass(frozen=True, slots=True)
class MembershipDecision:
    allowed: bool
    code: str | None = None
    message: str = ""


class RealmMembershipProvider:
    """Backend-authoritative realm sync authorization boundary.

    TODO(Stage 41 production wiring): replace this local allow stub with the
    Eternia backend route that maps server membership and server roles to
    pull/publish permissions, plus git credential brokering.
    """

    def authorize(self, realm: Realm, action: str) -> MembershipDecision:
        # ``realm`` is unused BY THIS IMPLEMENTATION and stays in the signature
        # deliberately: this is the authorization boundary, and the default
        # provider being realm-agnostic is a property of the default, not of
        # the contract. A real membership provider decides per realm, so
        # dropping the parameter here would force every future implementation
        # to widen the interface — and the 2026-08-19 dead-parameter sweep that
        # cut `build_snapshot`'s three pass-through stores deliberately left
        # this one, because "unused" and "not part of the question" are
        # different findings.
        if action not in {"pull", "publish", "status"}:
            return MembershipDecision(False, "invalid_request", f"unsupported sync action: {action}")
        return MembershipDecision(True)


#: The canonicalization chokepoint, whose BODY moved to
#: :mod:`agent_runtime.sync_text` on 2026-09-12
#: (``EterniaLauncher/docs/mission_control/planned/held-skill-publish-direction.md``
#: §4.1). This name stays as the alias every call site in this module — and
#: ``realm_sync.families.content_hash`` — already spells, so the lift changed
#: no behaviour anywhere. It moved because the SKILL lane needs the same rule for
#: its package hash and ``skill_promotion`` may not import this module (the pull
#: pipeline imports the promotion door; the dependency is one-directional).
_canonicalize_text_bytes = canonicalize_text_bytes


def _safe_display_path(path: Path) -> str:
    try:
        return path.relative_to(get_hermes_home()).as_posix()
    except ValueError:
        try:
            return path.relative_to(paths.store_root()).as_posix()
        except ValueError:
            return path.name
