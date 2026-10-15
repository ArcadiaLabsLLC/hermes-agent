"""The ONE per-entity admission guard for realm-sync pull appliers.

``pull_realm_sync`` runs ``_assert_no_secret_artifacts`` over the artifacts the
GENERIC write-loop maps — and only those. Every specialized applier
(``board_sync``, ``office_sync``, ``apply_skill_inbox_pull``,
``persona_config_sync``, ``profile_artifact_sync``) exists precisely because its
family is EXCLUDED from that loop (``_destination_for_sync_path`` → ``None``),
which means those families were never scanned on the way in. The persona-config
lane grew its own inline scan at ``c905569c1``; the others had none. This module
is that scan, lifted to one place so there is a single authority rather than
four drifting copies.

Two deliberate posture rules, both learned the hard way in this subsystem:

1. **Secrets are scanned everywhere.** The regex is
   ``agent_runtime.redaction``'s single-homed :data:`~agent_runtime.redaction.
   SECRET_ASSIGNMENT_RE`; the secret-ish path markers and the hard-excluded path
   parts are still ``realm_sync``'s (imported lazily). This module never defines
   a second copy of either. A pulled entity carrying a secret-shaped
   assignment is refused at the door. This is strictly *less* destructive than
   the generic loop's behaviour, which raises and aborts the whole pull: here one
   bad entity is refused and the pull continues (per-entity isolation).

2. **Portability is scanned only over WIRING, never over prose.**
   ``realm_sync._assert_portable_artifacts`` already documents why: a skill's
   ``SKILL.md``, a profile ``MEMORY.md``, an ``AGENTS.md`` or a board card
   description legitimately mentions absolute paths as English, and "a refusal
   that bricks a publish over a false positive" is a failure class this
   subsystem has already paid for. So free-text keys (:data:`PROSE_KEYS`) are
   pruned before the portability walk, and file BODIES are never portability
   -scanned at all — only structured payloads and path components are.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .redaction import SECRET_ASSIGNMENT_RE

__layer__ = "policy"

#: Free-text keys pruned before the portability walk, at ANY depth. These carry
#: operator/agent English (board card titles + descriptions + checklist text,
#: column titles, office folder names, actor display names), where an absolute
#: path is a legitimate mention and never live wiring.
PROSE_KEYS: frozenset[str] = frozenset(
    {
        "checklist",
        "description",
        "display_name",
        "folder",
        "folders",
        "name",
        "notes",
        "text",
        "title",
    }
)

#: Path components that can never appear in a pulled relative path. ``..``/``.``
#: are traversal; empty is malformed. Absolute/drive-letter/UNC shapes are
#: rejected by :func:`path_refusal` structurally rather than by name.
_UNSAFE_COMPONENTS = frozenset({"", ".", ".."})


# --- portability validation -------------------------------------------------

# A Windows drive-letter path (``X:\...`` / ``x:/...``) ANYWHERE in a value. The
# negative lookbehind keeps URL schemes out: ``http://host`` contains ``p://``
# but its ``p`` is preceded by ``t``. Case-insensitive by construction.
_DRIVE_LETTER_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")

# A UNC share (``\\host\share``). Written as two literal backslashes followed by
# a hostname component and a separator.
_UNC_RE = re.compile(r"\\\\[A-Za-z0-9_.-]+[\\/]")

# A POSIX-absolute path as the WHOLE value: leading ``/`` plus at least two
# whitespace-free segments (``/home/tony/repo``, ``/opt/hermes/bin``). Anchored
# and whitespace-free on purpose — an unanchored ``^/`` rule fires on prose like
# ``"/help /clear"`` and a refusal that bricks a publish over a display-name
# false positive is a failure class this file has already paid for. The known,
# accepted miss is a POSIX path containing spaces (``/home/my user/repo``);
# missing a rare path beats bricking every publish.
_POSIX_ABS_RE = re.compile(r"^/(?:[^/\s]+/)+[^/\s]*$")


def nonportable_reason(value: Any) -> str | None:
    """Return a typed reason when ``value`` is machine/installation-shaped.

    ``None`` means portable. Non-strings are always portable (numbers, bools).
    Whitespace cannot defeat the check: drive-letter/UNC are scanned anywhere in
    the raw string, and the POSIX rule runs on the stripped value.
    """

    if not isinstance(value, str):
        return None
    if _DRIVE_LETTER_RE.search(value):
        return "drive_letter_path"
    if _UNC_RE.search(value):
        return "unc_path"
    if _POSIX_ABS_RE.match(value.strip()):
        return "posix_absolute_path"
    return None


def find_nonportable_values(data: Any, *, prefix: str = "") -> list[dict[str, str]]:
    """Walk a projected structure and return EVERY machine-shaped leaf.

    Rows are ``{"key": <dotted path>, "reason": <typed>, "value": <preview>}``.
    All offenders are returned in one pass so the caller can name them in a
    single typed error (the "name ALL offenders" precedent) instead of making an
    operator re-run the publish once per bad key.
    """

    offenders: list[dict[str, str]] = []
    if isinstance(data, dict):
        for key in sorted(data, key=str):
            offenders.extend(find_nonportable_values(data[key], prefix=f"{prefix}.{key}" if prefix else str(key)))
        return offenders
    if isinstance(data, (list, tuple)):
        for index, item in enumerate(data):
            offenders.extend(find_nonportable_values(item, prefix=f"{prefix}[{index}]"))
        return offenders
    reason = nonportable_reason(data)
    if reason is not None:
        offenders.append({"key": prefix or "<root>", "reason": reason, "value": str(data)[:200]})
    return offenders


NONPORTABLE_HINT = (
    "Machine-shaped values cannot travel to another member (or another OS). "
    "Remove the absolute path from the persona definition, or express it "
    "portably — 'repo_scope' is already excluded from realm sync; use "
    "'repo_scope_label' for the human name and let each member bind their own "
    "checkout. MCP server commands/env are never published."
)


@dataclass(frozen=True, slots=True)
class Refusal:
    """One refused entity. Mirrors ``persona_config_sync._refusal``'s row shape
    (``{key, code, message}``) so every lane's ``refused`` list reads the same
    in a pull result and in Mission Control."""

    key: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "code": self.code, "message": self.message}


def _secret_assignment_re():
    # Eager import is safe now: the rule lives in stdlib-only
    # ``agent_runtime.redaction``, not in heavyweight ``realm_sync``. Kept as a
    # function so existing callers/monkeypatches keep their seam.
    return SECRET_ASSIGNMENT_RE


def path_refusal(rel: str) -> tuple[str, str] | None:
    """Typed refusal for an untrusted RELATIVE path from a pulled subtree.

    ``None`` means admissible. Covers traversal, absolute/drive-letter/UNC
    shapes, Windows reserved device names (a ``con``/``nul`` component crashes
    the write on Windows — a pull DoS the skill mirror already learned about),
    and the shared secret-ish / hard-excluded path markers.
    """

    from .realm_sync.families import _is_hard_excluded_path, _is_secretish_path
    from .paths import is_windows_reserved_component

    text = str(rel or "").replace("\\", "/")
    if not text.strip():
        return ("unsafe_path", "empty relative path")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return ("unsafe_path", f"absolute path is never a pull destination: {text}")
    parts = tuple(part for part in text.split("/"))
    for part in parts:
        if part in _UNSAFE_COMPONENTS:
            return ("unsafe_path", f"unsafe path component in {text!r}")
        if is_windows_reserved_component(part):
            return ("reserved_path_component", f"reserved device name component in {text!r}")
    if _is_secretish_path(text):
        return ("secretish_path", f"path matches a secret marker: {text}")
    if _is_hard_excluded_path(text):
        return ("hard_excluded_path", f"path is hard-excluded from realm sync: {text}")
    return None


def content_refusal(data: bytes) -> tuple[str, str] | None:
    """Typed refusal for a pulled FILE BODY. Secret-shaped assignments only —
    deliberately no portability walk (see the module docstring: file bodies are
    prose)."""

    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001 — an undecodable blob carries no assignment
        return None
    if _secret_assignment_re().search(text):
        return ("secret_shaped_value", "file content carries a secret-shaped assignment")
    return None


def prune_prose(value: Any, prose_keys: frozenset[str] = PROSE_KEYS) -> Any:
    """Drop every ``prose_keys`` branch so the portability walk only ever sees
    wiring. Recursive; containers are rebuilt, scalars pass through. Pass an
    empty set for a payload that is 100% wiring (a persona definition, whose keys
    are themselves an allowlist) so nothing is exempted."""

    if isinstance(value, dict):
        return {
            key: prune_prose(item, prose_keys)
            for key, item in value.items()
            if str(key) not in prose_keys
        }
    if isinstance(value, (list, tuple)):
        return [prune_prose(item, prose_keys) for item in value]
    return value


def _flatten_assignments(value: Any, *, out: list[str] | None = None) -> str:
    """Render a structure as unquoted ``key=value`` lines for the assignment
    scanner. ``json.dumps`` writes ``"token": "…"``; the closing quote on the key
    defeats ``\\btoken\\b\\s*[:=]``, so a secret carried as a FIELD would slip
    through a raw-dump scan. Rendering it as ``token=…`` closes that."""

    rows = [] if out is None else out
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list, tuple)):
                _flatten_assignments(item, out=rows)
            else:
                rows.append(f"{key}={item}")
    elif isinstance(value, (list, tuple)):
        for item in value:
            _flatten_assignments(item, out=rows)
    return "\n".join(rows)


def payload_refusal(
    payload: Any,
    *,
    prefix: str = "",
    check_portability: bool = True,
    prose_keys: frozenset[str] = PROSE_KEYS,
) -> tuple[str, str] | None:
    """Typed refusal for a pulled STRUCTURED entity (a board card, an office
    actor, a persona definition).

    Runs the secret-assignment scan over the whole payload and — when
    ``check_portability`` — the shared machine-shaped-value walk over the
    prose-pruned payload. ALL portability offenders are named in one message
    (the "name ALL offenders" precedent) so an operator sees the full picture.
    """

    try:
        encoded = json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        encoded = str(payload)
    # Two passes, because the scanner is an ASSIGNMENT regex: the raw dump catches
    # a secret embedded inside a value (``"display_name": "api_key: sk-…"`` — the
    # persona-config lane's shape), while the flattened pass catches a secret
    # carried as a FIELD, which JSON quoting (``"token": "…"``) otherwise hides
    # from ``\btoken\b\s*[:=]``.
    if _secret_assignment_re().search(encoded) or _secret_assignment_re().search(_flatten_assignments(payload)):
        return ("secret_shaped_value", "entity carries a secret-shaped assignment")
    if check_portability:
        offenders = find_nonportable_values(prune_prose(payload, prose_keys), prefix=prefix)
        if offenders:
            return (
                "nonportable_path",
                "machine-shaped value(s): " + ", ".join(row["key"] for row in offenders),
            )
    return None


def refuse_entity(
    key: str,
    *,
    relative_paths: tuple[str, ...] = (),
    payload: Any = None,
    blobs: tuple[bytes, ...] = (),
    check_portability: bool = True,
    prose_keys: frozenset[str] = PROSE_KEYS,
    prefix: str = "",
) -> Refusal | None:
    """One admission decision for one entity across all of its evidence.

    Returns the FIRST refusal (path → payload → body) or ``None``. Callers keep
    per-entity isolation: refuse this entity, record the row, keep pulling.
    """

    for rel in relative_paths:
        found = path_refusal(rel)
        if found is not None:
            return Refusal(key, found[0], found[1])
    if payload is not None:
        found = payload_refusal(
            payload,
            prefix=prefix or key,
            check_portability=check_portability,
            prose_keys=prose_keys,
        )
        if found is not None:
            return Refusal(key, found[0], found[1])
    for blob in blobs:
        found = content_refusal(blob)
        if found is not None:
            return Refusal(key, found[0], found[1])
    return None


def refuse_package(key: str, root: Path) -> Refusal | None:
    """Admission decision for a whole multi-file package (a pulled skill).

    Every file's relative path and body is scanned; portability is NOT — a
    skill's documentation legitimately names absolute paths. ``root`` missing is
    admissible (nothing to admit).
    """

    if not root.is_dir():
        return None
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        found = path_refusal(f"{key}/{rel}")
        if found is not None:
            return Refusal(key, found[0], found[1])
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if len(data) > 1_000_000:
            continue  # matches ``_file_contains_secret_assignment``'s size bound
        found = content_refusal(data)
        if found is not None:
            return Refusal(key, found[0], f"{found[1]} ({rel})")
    return None
